"""오케스트레이션: 시드 → 시총 상위 100 → 업종 제외 → ROIC 상위 30.

수집 순서가 중요하다. 종목당 full fetch 는 6회 호출이므로
시드 전체(지역당 100~200개)에 돌리면 Yahoo 차단이 걸린다.
그래서 2패스로 나눈다:
  1패스  info 만 → USD 환산 시총 랭킹 → 상위 100 확정
  2패스  상위 100 에 대해서만 재무제표 + 전체 주가 히스토리
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from .config import DIVIDEND_WHT, REGIONS, ScreenParams
from .exclusions import sector_exclusion_reason
from .fx import FxRates
from .prices import PriceStats, price_stats
from .provider import CompanyRaw, FetchError, Provider
from .roic import RoicResult, compute_roic
from .universe import exchange_label, load_cn_universe_from_akshare, load_seeds

log = logging.getLogger(__name__)


@dataclass
class Row:
    region: str
    ticker: str
    name: str | None
    sector: str | None
    industry: str | None
    exchange: str | None
    currency: str | None
    market_cap: float | None = None
    market_cap_usd: float | None = None
    mcap_rank: int | None = None
    ev_to_ebitda: float | None = None
    ev_to_ebitda_source: str = ""
    roic: RoicResult | None = None
    price: PriceStats = field(default_factory=PriceStats)
    excluded_reason: str | None = None

    @property
    def roic_value(self) -> float | None:
        return self.roic.roic if self.roic else None


@dataclass
class ScreenResult:
    params: ScreenParams
    generated_at: dt.datetime
    top: dict[str, list[Row]] = field(default_factory=dict)  # region → ROIC 상위 N
    universe: dict[str, list[Row]] = field(default_factory=dict)  # region → 시총 상위 100
    excluded: list[Row] = field(default_factory=list)
    errors: list[FetchError] = field(default_factory=list)
    fx: dict[str, float | None] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
def _ev_to_ebitda(raw: CompanyRaw, roic: RoicResult | None) -> tuple[float | None, str]:
    """EV/EBITDA. Yahoo 제공값을 우선하고, 없으면 직접 계산한다."""
    if raw.ev_to_ebitda is not None and raw.ev_to_ebitda != 0:
        return raw.ev_to_ebitda, "Yahoo enterpriseToEbitda"

    if not roic or not roic.ebitda_total or roic.coverage_days <= 0:
        return None, "계산 불가(EBITDA 결측)"

    ebitda_annual = roic.ebitda_total / (roic.coverage_days / 365.25)
    if ebitda_annual <= 0:
        return None, "계산 불가(EBITDA 음수)"

    ev = raw.enterprise_value
    if ev is None:
        if raw.market_cap is None:
            return None, "계산 불가(EV 결측)"
        net_debt = (roic.total_debt_last or 0.0) - (roic.excess_cash_last or 0.0)
        ev = raw.market_cap + net_debt
    return ev / ebitda_annual, "직접계산 EV/연율화EBITDA"


def run_screen(
    provider: Provider,
    regions: list[str],
    params: ScreenParams,
    *,
    seed_dir=None,
    use_akshare_for_cn: bool = False,
    on_progress=None,
) -> ScreenResult:
    result = ScreenResult(params=params, generated_at=dt.datetime.now())
    fx = FxRates(provider.fx_quote)

    def progress(msg: str) -> None:
        # 콜백이 있으면 그쪽만 쓴다 (둘 다 하면 같은 줄이 두 번 찍힌다)
        if on_progress:
            on_progress(msg)
        else:
            log.info(msg)

    for region in regions:
        if region not in REGIONS:
            raise ValueError(f"알 수 없는 지역: {region}")

        # ---- 후보 티커 ------------------------------------------------
        tickers: list[str] = []
        if region == "cn" and use_akshare_for_cn:
            try:
                tickers = load_cn_universe_from_akshare(limit=300)
                progress(f"[cn] akshare 전종목 시총 스냅샷에서 {len(tickers)}종목 확보")
            except Exception as exc:  # noqa: BLE001
                result.notes.append(f"[cn] akshare 실패 → 시드 파일 사용: {exc}")
                progress(f"[cn] akshare 실패, 시드 파일로 대체: {exc}")
        if not tickers:
            tickers = load_seeds(region, seed_dir)
        # 홍콩 종목은 중국 지역 시드에 함께 들어 있다
        progress(f"[{region}] 후보 {len(tickers)}종목 — 1패스(시총) 수집 시작")

        # ---- 1패스: 시총 ---------------------------------------------
        quotes: list[Row] = []
        for i, tk in enumerate(tickers, 1):
            try:
                raw = provider.fetch_quote(tk)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(FetchError(tk, "quote", str(exc)))
                continue
            if raw.market_cap is None:
                result.errors.append(
                    FetchError(tk, "quote", "시가총액 없음 — 티커 오류 또는 상장폐지 가능")
                )
                continue
            quotes.append(
                Row(
                    region=region,
                    ticker=tk,
                    name=raw.name,
                    sector=raw.sector,
                    industry=raw.industry,
                    exchange=raw.exchange or exchange_label(tk),
                    currency=raw.currency,
                    market_cap=raw.market_cap,
                    market_cap_usd=fx.to_usd(raw.market_cap, raw.currency),
                )
            )
            if i % 25 == 0:
                progress(f"[{region}] 1패스 {i}/{len(tickers)}")

        unpriced = [r for r in quotes if r.market_cap_usd is None]
        for r in unpriced:
            result.notes.append(f"[{region}] {r.ticker}: {r.currency} 환율 조회 실패 — 순위 제외")
        ranked = sorted(
            (r for r in quotes if r.market_cap_usd is not None),
            key=lambda r: r.market_cap_usd,
            reverse=True,
        )[: params.top_n_marketcap]
        for i, r in enumerate(ranked, 1):
            r.mcap_rank = i
        result.universe[region] = ranked
        progress(f"[{region}] 시총 상위 {len(ranked)}종목 확정 — 2패스 시작")

        # ---- 업종 제외 (재무 수집 전에 걸러 호출을 아낀다) ------------
        candidates: list[Row] = []
        for r in ranked:
            reason = sector_exclusion_reason(r.sector, r.industry)
            if reason:
                r.excluded_reason = reason
                result.excluded.append(r)
            else:
                candidates.append(r)
        progress(
            f"[{region}] 업종 제외 {len(ranked) - len(candidates)}종목, "
            f"ROIC 계산 대상 {len(candidates)}종목"
        )

        # ---- 2패스: 재무 + 주가 --------------------------------------
        scored: list[Row] = []
        for i, r in enumerate(candidates, 1):
            try:
                raw = provider.fetch(r.ticker)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(FetchError(r.ticker, "full", str(exc)))
                r.excluded_reason = f"재무 수집 실패: {exc}"
                result.excluded.append(r)
                continue

            r.roic = compute_roic(
                annual_income=raw.annual_income,
                interim_income=raw.interim_income,
                annual_balance=raw.annual_balance,
                interim_balance=raw.interim_balance,
                window_start=params.window_start,
                window_end=params.window_end,
                region=region,
                params=params.roic,
            )
            r.price = price_stats(raw.bars)
            r.ev_to_ebitda, r.ev_to_ebitda_source = _ev_to_ebitda(raw, r.roic)

            reason = _quality_reason(r, params)
            if reason:
                r.excluded_reason = reason
                result.excluded.append(r)
            else:
                scored.append(r)
            if i % 10 == 0:
                progress(f"[{region}] 2패스 {i}/{len(candidates)}")

        scored.sort(key=lambda r: r.roic_value, reverse=True)
        result.top[region] = scored[: params.top_n_roic]
        progress(
            f"[{region}] 완료 — ROIC 계산 성공 {len(scored)}종목, "
            f"상위 {len(result.top[region])}종목 선정"
        )

    result.fx = fx.snapshot()
    result.notes.append(
        "배당 원천징수(참고): "
        + " / ".join(f"{REGIONS[r].name} {DIVIDEND_WHT[r]}" for r in regions if r in DIVIDEND_WHT)
    )
    return result


def _quality_reason(r: Row, params: ScreenParams) -> str | None:
    """ROIC 결과를 순위에 올릴 수 있는지 판정한다."""
    res = r.roic
    if res is None or res.roic is None:
        detail = "; ".join(res.warnings) if res and res.warnings else "재무데이터 부족"
        return f"ROIC 계산 실패: {detail}"

    if res.coverage_ratio < params.roic.min_coverage_ratio:
        return f"기간 커버리지 부족({res.coverage_ratio:.0%})"

    ic_usd = r.market_cap_usd and res.invested_capital_avg and r.market_cap
    if ic_usd:
        # 시총의 통화 → USD 배율을 재사용해 투하자본을 USD 로 환산한다
        scale = r.market_cap_usd / r.market_cap
        if res.invested_capital_avg * scale < params.roic.min_invested_capital_usd:
            return (
                f"투하자본 과소(${res.invested_capital_avg * scale / 1e6:.0f}M "
                f"< ${params.roic.min_invested_capital_usd / 1e6:.0f}M) — ROIC 왜곡"
            )
    return None
