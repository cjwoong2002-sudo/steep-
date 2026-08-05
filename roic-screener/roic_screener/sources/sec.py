"""미국 — SEC XBRL companyfacts 교차검증.

무료·API 키 불필요. 단 두 가지 규칙이 있다:
  1. User-Agent 헤더에 연락처를 반드시 넣어야 한다 (없으면 403)
  2. 초당 10건 제한

용도는 "yfinance 값이 맞는지 확인"이다. ROIC 전체를 SEC 로 재계산하지는 않는다
(us-gaap 태그 선택·회사별 변형 처리 비용이 커서 별개 프로젝트가 된다).

사용:
    from roic_screener.sources.sec import SecClient
    c = SecClient(user_agent="이름 you@example.com")
    print(c.annual_values("AAPL", "OperatingIncomeLoss"))
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
import urllib.request

log = logging.getLogger(__name__)

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# 검증에 쓸 만한 us-gaap 태그
USEFUL_TAGS = (
    "OperatingIncomeLoss",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeTaxExpenseBenefit",
    "StockholdersEquity",
    "Assets",
    "Goodwill",
    "CashAndCashEquivalentsAtCarryingValue",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
)


class SecClient:
    def __init__(self, user_agent: str, min_interval: float = 0.15):
        if "@" not in user_agent:
            raise ValueError(
                "SEC 는 User-Agent 에 연락 가능한 이메일을 요구합니다. "
                "예: 'Hong Gildong hong@example.com'"
            )
        self.user_agent = user_agent
        self.min_interval = min_interval
        self._last = 0.0
        self._tickers: dict[str, int] | None = None

    def _get(self, url: str) -> dict:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(
            url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip

                raw = gzip.decompress(raw)
        self._last = time.monotonic()
        return json.loads(raw)

    def cik_of(self, ticker: str) -> int | None:
        if self._tickers is None:
            data = self._get(TICKER_MAP_URL)
            self._tickers = {
                str(row["ticker"]).upper(): int(row["cik_str"]) for row in data.values()
            }
        return self._tickers.get(ticker.upper().replace("-", "."))

    def annual_values(self, ticker: str, tag: str) -> dict[dt.date, float]:
        """연간(10-K) 값 {기말: 값}. 같은 기말이 여러 번 정정되면 최신 접수분을 쓴다."""
        cik = self.cik_of(ticker)
        if cik is None:
            log.warning("SEC 에서 CIK 를 못 찾음: %s", ticker)
            return {}
        facts = self._get(FACTS_URL.format(cik=cik))
        units = (facts.get("facts", {}).get("us-gaap", {}).get(tag, {}) or {}).get("units", {})
        series = units.get("USD") or next(iter(units.values()), [])

        best: dict[dt.date, tuple[str, float]] = {}
        for item in series:
            if item.get("form") not in ("10-K", "10-K/A", "20-F"):
                continue
            if item.get("fp") != "FY":
                continue
            try:
                end = dt.date.fromisoformat(item["end"])
                val = float(item["val"])
            except (KeyError, ValueError, TypeError):
                continue
            filed = str(item.get("filed", ""))
            prev = best.get(end)
            if prev is None or filed > prev[0]:
                best[end] = (filed, val)
        return {k: v[1] for k, v in sorted(best.items())}
