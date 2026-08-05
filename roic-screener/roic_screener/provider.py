"""데이터 수집 계층.

`Provider` 프로토콜만 지키면 어떤 소스로도 갈아끼울 수 있다.
기본 구현은 yfinance 다 — 5개 지역을 무료로 한 번에 덮는 유일한 백본이기 때문이다.

yfinance 는 비공식 래퍼라서 (a) 계정 라벨이 예고 없이 바뀌고 (b) 과호출 시
IP 차단이 걸린다. 그래서 이 계층은 처음부터 다음을 전제로 짰다:

* 디스크 캐시 — 같은 날 재실행은 네트워크를 전혀 타지 않는다
* 호출 간 대기 + 지터 — 차단 회피
* 지수 백오프 재시도
* 실패는 예외를 던지지 않고 `FetchError` 로 수집되어 엑셀 '조회실패' 시트에 남는다
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .fields import normalize_values
from .prices import Bar
from .roic import PeriodFacts

log = logging.getLogger(__name__)


@dataclass
class CompanyRaw:
    ticker: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    currency: str | None = None
    exchange: str | None = None
    market_cap: float | None = None
    ev_to_ebitda: float | None = None
    enterprise_value: float | None = None
    country: str | None = None
    annual_income: list[PeriodFacts] = field(default_factory=list)
    interim_income: list[PeriodFacts] = field(default_factory=list)
    annual_balance: list[PeriodFacts] = field(default_factory=list)
    interim_balance: list[PeriodFacts] = field(default_factory=list)
    bars: list[Bar] = field(default_factory=list)
    source: str = "yfinance"


@dataclass
class FetchError:
    ticker: str
    stage: str
    message: str


class Provider(Protocol):
    def fetch_quote(self, ticker: str) -> CompanyRaw: ...
    def fetch(self, ticker: str) -> CompanyRaw: ...
    def fx_quote(self, pair: str) -> float | None: ...


# ---------------------------------------------------------------------------
# 캐시
# ---------------------------------------------------------------------------
class DiskCache:
    def __init__(self, root: Path, ttl_days: float = 1.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl = dt.timedelta(days=ttl_days)

    def _path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in key)
        return self.root / f"{safe}.json"

    def get(self, key: str) -> dict | None:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
            stamped = dt.datetime.fromisoformat(payload["_fetched"])
        except Exception:
            return None
        if dt.datetime.now() - stamped > self.ttl:
            return None
        return payload

    def put(self, key: str, payload: dict) -> None:
        payload = dict(payload)
        payload["_fetched"] = dt.datetime.now().isoformat(timespec="seconds")
        tmp = self._path(key).with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8"
        )
        tmp.replace(self._path(key))


# ---------------------------------------------------------------------------
# 직렬화 헬퍼
# ---------------------------------------------------------------------------
def _periods_to_json(periods: list[PeriodFacts]) -> dict[str, dict[str, float]]:
    return {p.end.isoformat(): p.values for p in periods}


def _periods_from_json(raw: dict, kind: str) -> list[PeriodFacts]:
    out = []
    for datestr, values in (raw or {}).items():
        try:
            end = dt.date.fromisoformat(datestr[:10])
        except ValueError:
            continue
        out.append(PeriodFacts(end=end, values={k: float(v) for k, v in values.items()}, kind=kind))
    return sorted(out, key=lambda p: p.end)


def _bars_to_json(bars: list[Bar]) -> list[list]:
    return [[b.date.isoformat(), b.close, b.split] for b in bars]


def _bars_from_json(raw: list) -> list[Bar]:
    out = []
    for row in raw or []:
        try:
            out.append(Bar(dt.date.fromisoformat(row[0][:10]), float(row[1]), float(row[2])))
        except (ValueError, TypeError, IndexError):
            continue
    return out


INFO_KEYS = (
    "shortName",
    "longName",
    "sector",
    "industry",
    "currency",
    "financialCurrency",
    "exchange",
    "fullExchangeName",
    "marketCap",
    "enterpriseValue",
    "enterpriseToEbitda",
    "country",
    "quoteType",
)


# ---------------------------------------------------------------------------
# yfinance 구현
# ---------------------------------------------------------------------------
class YFinanceProvider:
    """yfinance 백본. 임포트는 실제로 쓸 때만 한다(테스트는 이 클래스를 안 쓴다)."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        cache_ttl_days: float = 1.0,
        min_interval: float = 1.2,
        max_retries: int = 3,
        history_period: str = "max",
    ):
        self.cache = DiskCache(cache_dir, cache_ttl_days)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.history_period = history_period
        self._last_call = 0.0
        self._yf = None

    # -- 저수준 --------------------------------------------------------
    @property
    def yf(self):
        if self._yf is None:
            import yfinance  # noqa: PLC0415 - 지연 임포트 의도적

            self._yf = yfinance
        return self._yf

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.4))
        self._last_call = time.monotonic()

    def _retry(self, label: str, fn):
        last: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 - 래퍼가 던지는 예외 종류가 다양하다
                last = exc
                backoff = 2**attempt
                log.warning("%s 실패 (%d/%d): %s — %ds 후 재시도",
                            label, attempt + 1, self.max_retries, exc, backoff)
                time.sleep(backoff)
        raise RuntimeError(f"{label}: {last}") from last

    @staticmethod
    def _df_to_periods(df, kind: str) -> list[PeriodFacts]:
        if df is None or getattr(df, "empty", True):
            return []
        periods: list[PeriodFacts] = []
        for col in df.columns:
            try:
                end = col.date() if hasattr(col, "date") else dt.date.fromisoformat(str(col)[:10])
            except (ValueError, AttributeError):
                continue
            raw = {str(idx): df.at[idx, col] for idx in df.index}
            periods.append(PeriodFacts(end=end, values=normalize_values(raw), kind=kind))
        return sorted(periods, key=lambda p: p.end)

    @staticmethod
    def _history_to_bars(hist) -> list[Bar]:
        if hist is None or getattr(hist, "empty", True):
            return []
        bars: list[Bar] = []
        splits = "Stock Splits" in hist.columns
        for idx, row in hist.iterrows():
            try:
                d = idx.date() if hasattr(idx, "date") else dt.date.fromisoformat(str(idx)[:10])
                close = float(row["Close"])
            except (ValueError, TypeError, KeyError, AttributeError):
                continue
            if close != close or close <= 0:
                continue
            sp = 0.0
            if splits:
                try:
                    sp = float(row["Stock Splits"])
                except (ValueError, TypeError):
                    sp = 0.0
                if sp != sp:
                    sp = 0.0
            bars.append(Bar(d, close, sp))
        return bars

    # -- 공개 API ------------------------------------------------------
    def fetch_quote(self, ticker: str) -> CompanyRaw:
        """1차 패스: 시총 순위를 매기는 데 필요한 info 만 가져온다.

        재무제표와 전체 주가 히스토리는 종목당 5회 추가 호출이라
        시드 전체(지역당 100~200개)에 대해 돌리면 차단 위험이 크다.
        상위 100 을 먼저 확정하고 그 종목만 full fetch 한다.
        """
        cached = self.cache.get(f"q_{ticker}")
        if cached:
            return self._from_payload(ticker, cached)
        t = self.yf.Ticker(ticker)
        info: dict[str, Any] = self._retry(f"{ticker} info", lambda: dict(t.info or {}))
        payload = {"info": {k: info.get(k) for k in INFO_KEYS}}
        self.cache.put(f"q_{ticker}", payload)
        return self._from_payload(ticker, payload)

    def fetch(self, ticker: str) -> CompanyRaw:
        cached = self.cache.get(f"co_{ticker}")
        if cached:
            return self._from_payload(ticker, cached)

        t = self.yf.Ticker(ticker)
        quote_cache = self.cache.get(f"q_{ticker}")
        if quote_cache:
            info: dict[str, Any] = quote_cache.get("info") or {}
        else:
            info = self._retry(f"{ticker} info", lambda: dict(t.info or {}))
        payload = {
            "info": {k: info.get(k) for k in INFO_KEYS},
            "annual_income": _periods_to_json(
                self._df_to_periods(self._retry(f"{ticker} IS(A)", lambda: t.income_stmt), "FY")
            ),
            "interim_income": _periods_to_json(
                self._df_to_periods(
                    self._retry(f"{ticker} IS(Q)", lambda: t.quarterly_income_stmt), "INTERIM"
                )
            ),
            "annual_balance": _periods_to_json(
                self._df_to_periods(self._retry(f"{ticker} BS(A)", lambda: t.balance_sheet), "FY")
            ),
            "interim_balance": _periods_to_json(
                self._df_to_periods(
                    self._retry(f"{ticker} BS(Q)", lambda: t.quarterly_balance_sheet), "INTERIM"
                )
            ),
            "bars": _bars_to_json(
                self._history_to_bars(
                    self._retry(
                        f"{ticker} history",
                        lambda: t.history(period=self.history_period, auto_adjust=False),
                    )
                )
            ),
        }
        self.cache.put(f"co_{ticker}", payload)
        return self._from_payload(ticker, payload)

    @staticmethod
    def _from_payload(ticker: str, payload: dict) -> CompanyRaw:
        info = payload.get("info") or {}
        return CompanyRaw(
            ticker=ticker,
            name=info.get("longName") or info.get("shortName"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            currency=info.get("currency"),
            exchange=info.get("fullExchangeName") or info.get("exchange"),
            market_cap=_num(info.get("marketCap")),
            ev_to_ebitda=_num(info.get("enterpriseToEbitda")),
            enterprise_value=_num(info.get("enterpriseValue")),
            country=info.get("country"),
            annual_income=_periods_from_json(payload.get("annual_income"), "FY"),
            interim_income=_periods_from_json(payload.get("interim_income"), "INTERIM"),
            annual_balance=_periods_from_json(payload.get("annual_balance"), "FY"),
            interim_balance=_periods_from_json(payload.get("interim_balance"), "INTERIM"),
            bars=_bars_from_json(payload.get("bars")),
        )

    def fx_quote(self, pair: str) -> float | None:
        cached = self.cache.get(f"fx_{pair}")
        if cached:
            return _num(cached.get("rate"))
        try:
            t = self.yf.Ticker(pair)
            hist = self._retry(f"{pair} fx", lambda: t.history(period="5d", auto_adjust=False))
            bars = self._history_to_bars(hist)
            rate = bars[-1].close if bars else None
        except Exception as exc:  # noqa: BLE001
            log.warning("환율 %s 조회 실패: %s", pair, exc)
            return None
        if rate:
            self.cache.put(f"fx_{pair}", {"rate": rate})
        return rate


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f
