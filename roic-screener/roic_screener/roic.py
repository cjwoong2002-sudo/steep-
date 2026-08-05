"""ROIC 계산 엔진 — 순수 함수. 네트워크도 pandas도 쓰지 않는다.

정의 (이 파일이 유일한 기준이다):

    실효세율 t = clamp( Σ법인세비용 / Σ세전이익 , 10%, 40% )
                 계산 불가 시 지역 법정세율

    NOPAT_창 = Σ EBIT(창 구간) × (1 − t)

    투하자본 IC = 총차입금 + 자본총계(비지배지분 포함)
                  − 초과현금
      초과현금 = max(0, 현금및단기금융상품 − 매출 × 2%)
      (옵션) − 영업권

    ROIC = ( NOPAT_창 / (커버일수/365.25) ) / 평균IC

* EBIT 은 비지배지분 차감 전 이익이므로 자본도 비지배지분을 포함시켜 짝을 맞춘다.
* 평균IC 는 창 구간 안팎의 모든 재무상태표 스냅샷(직전 기말 포함) 평균이다.
  기말 한 시점만 쓰면 대규모 인수·자사주 매입 직후 ROIC가 왜곡된다.
* 리스부채는 Yahoo 의 'Total Debt' 에 대체로 포함된다(IFRS 필수 계상).
  포함 여부가 회사마다 다를 수 있어 결과 시트에 총차입금 원값을 그대로 노출한다.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace

from .config import DAYS_PER_YEAR, RoicParams
from .fields import norm, pick

MAX_INFERRED_INTERIM_DAYS = 200
DEFAULT_INTERIM_DAYS = 92
DEFAULT_ANNUAL_DAYS = 365


@dataclass
class PeriodFacts:
    """한 보고기간의 정규화된 계정 값."""

    end: dt.date
    values: dict[str, float]
    kind: str = "FY"  # 'FY' | 'INTERIM'
    start: dt.date | None = None

    @property
    def days(self) -> int:
        if self.start is None:
            return 0
        return (self.end - self.start).days + 1


@dataclass
class RoicResult:
    roic: float | None
    nopat_annualized: float | None
    ebit_total: float | None
    revenue_total: float | None
    ebitda_total: float | None
    tax_rate: float | None
    tax_rate_source: str
    invested_capital_avg: float | None
    ic_snapshots: int
    total_debt_last: float | None
    equity_last: float | None
    excess_cash_last: float | None
    goodwill_last: float | None
    coverage_start: dt.date | None
    coverage_end: dt.date | None
    coverage_days: int
    coverage_ratio: float
    periods_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.roic is not None


# ---------------------------------------------------------------------------
# 기간 시작일 추정
# ---------------------------------------------------------------------------
def infer_starts(periods: list[PeriodFacts]) -> list[PeriodFacts]:
    """보고서에는 기말만 있으므로 직전 기말로부터 시작일을 역산한다.

    입력을 변형하지 않는다 — 호출자가 같은 리스트를 재사용할 수 있어야 한다.
    """
    out = [replace(p) for p in sorted(periods, key=lambda p: p.end)]
    for i, p in enumerate(out):
        if p.start is not None:
            continue
        prev_end = out[i - 1].end if i > 0 else None
        if prev_end is not None:
            gap = (p.end - prev_end).days
            limit = (
                DEFAULT_ANNUAL_DAYS + 20
                if p.kind == "FY"
                else MAX_INFERRED_INTERIM_DAYS
            )
            if 0 < gap <= limit:
                p.start = prev_end + dt.timedelta(days=1)
                continue
        span = DEFAULT_ANNUAL_DAYS if p.kind == "FY" else DEFAULT_INTERIM_DAYS
        p.start = p.end - dt.timedelta(days=span - 1)
    return out


def select_window_periods(
    annual: list[PeriodFacts],
    interim: list[PeriodFacts],
    window_start: dt.date,
    window_end: dt.date,
) -> tuple[list[PeriodFacts], list[str]]:
    """창 구간을 겹침 없이 덮는 보고기간을 고른다.

    1) 창 안에 온전히 들어가는 연간 기간을 먼저 채운다.
    2) 마지막 연간 기말 이후 ~ 창 종료까지를 분기/반기로 이어붙인다.
    3) 연간이 하나도 없으면 분기/반기만으로 구성한다.
    """
    warns: list[str] = []
    annual = infer_starts(list(annual))
    interim = infer_starts(list(interim))

    chosen = [
        p
        for p in annual
        if p.start is not None
        and p.start >= window_start - dt.timedelta(days=15)
        and p.end <= window_end
    ]

    cursor = chosen[-1].end if chosen else window_start - dt.timedelta(days=1)
    if not chosen:
        warns.append("창 구간에 온전한 연간보고 없음 — 분기/반기만으로 계산")

    for p in interim:
        if p.start is None or p.end > window_end:
            continue
        if p.end <= cursor:
            continue  # 이미 연간보고에 포함된 기간(예: FY의 4분기)
        if p.start <= cursor:
            # 시작일은 추정값이다. 직전 기말과 며칠 겹치는 건 추정 오차이므로 보정한다.
            # (3월 결산사의 1분기를 92일로 역산하면 3/31 에 걸려 통째로 누락된다)
            if (cursor - p.start).days <= 5:
                p = replace(p, start=cursor + dt.timedelta(days=1))
            else:
                warns.append(
                    f"{p.end.isoformat()} 보고기간이 직전 기말과 실제로 겹쳐 제외 "
                    "(중복 계상 방지)"
                )
                continue
        chosen.append(p)
        cursor = p.end

    if not chosen:
        warns.append("창 구간을 덮는 보고기간이 없음")
    return chosen, warns


# ---------------------------------------------------------------------------
# 계정 합계
# ---------------------------------------------------------------------------
def _ebit_of(v: dict[str, float]) -> float | None:
    ebit = pick(v, "ebit")
    if ebit is not None:
        return ebit
    # EBIT/영업이익이 없으면 세전이익 + 이자비용으로 근사한다.
    pretax = pick(v, "pretax_income")
    interest = pick(v, "interest_expense")
    if pretax is not None and interest is not None:
        return pretax + abs(interest)
    return None


def _ebitda_of(v: dict[str, float]) -> float | None:
    ebitda = pick(v, "ebitda")
    if ebitda is not None:
        return ebitda
    ebit = _ebit_of(v)
    da = pick(v, "depreciation_amortization")
    if ebit is not None and da is not None:
        return ebit + abs(da)
    return None


def _sum(periods: list[PeriodFacts], fn) -> tuple[float | None, int]:
    total = 0.0
    hits = 0
    for p in periods:
        val = fn(p.values)
        if val is None:
            continue
        total += val
        hits += 1
    return (total if hits else None), hits


# ---------------------------------------------------------------------------
# 투하자본
# ---------------------------------------------------------------------------
@dataclass
class InvestedCapital:
    value: float | None
    total_debt: float | None
    equity: float | None
    excess_cash: float | None
    goodwill: float | None


def invested_capital(
    bs: dict[str, float],
    revenue_annualized: float | None,
    params: RoicParams,
) -> InvestedCapital:
    """한 시점 재무상태표에서 투하자본을 계산한다."""
    debt = pick(bs, "total_debt")
    if debt is None:
        lt = pick(bs, "long_term_debt")
        cur = pick(bs, "current_debt")
        if lt is not None or cur is not None:
            debt = (lt or 0.0) + (cur or 0.0)

    equity = pick(bs, "equity_incl_minority")
    if equity is None:
        se = pick(bs, "stockholders_equity")
        if se is not None:
            equity = se + (pick(bs, "minority_interest") or 0.0)

    # '현금및현금성자산및단기금융상품' 합계 계정이 있으면 그것만 쓴다.
    # 없을 때만 현금 + 단기투자를 더한다(있는 계정을 두 번 더하지 않기 위함).
    combined = bs.get(norm("Cash Cash Equivalents And Short Term Investments"))
    if combined is not None:
        total_cash = combined
    else:
        total_cash = (pick(bs, "cash_and_sti") or 0.0) + (
            pick(bs, "short_term_investments") or 0.0
        )

    goodwill = pick(bs, "goodwill")

    if equity is None:
        return InvestedCapital(None, debt, equity, None, goodwill)

    op_cash_need = (revenue_annualized or 0.0) * params.operating_cash_pct
    excess_cash = max(0.0, total_cash - op_cash_need)

    ic = (debt or 0.0) + equity - excess_cash
    if params.exclude_goodwill and goodwill:
        ic -= goodwill
    return InvestedCapital(ic, debt, equity, excess_cash, goodwill)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def compute_roic(
    *,
    annual_income: list[PeriodFacts],
    interim_income: list[PeriodFacts],
    annual_balance: list[PeriodFacts],
    interim_balance: list[PeriodFacts],
    window_start: dt.date,
    window_end: dt.date,
    region: str,
    params: RoicParams,
) -> RoicResult:
    warnings: list[str] = []
    empty = RoicResult(
        roic=None,
        nopat_annualized=None,
        ebit_total=None,
        revenue_total=None,
        ebitda_total=None,
        tax_rate=None,
        tax_rate_source="n/a",
        invested_capital_avg=None,
        ic_snapshots=0,
        total_debt_last=None,
        equity_last=None,
        excess_cash_last=None,
        goodwill_last=None,
        coverage_start=None,
        coverage_end=None,
        coverage_days=0,
        coverage_ratio=0.0,
        warnings=warnings,
    )

    periods, warns = select_window_periods(
        annual_income, interim_income, window_start, window_end
    )
    warnings.extend(warns)
    if not periods:
        return empty

    coverage_days = sum(p.days for p in periods)
    window_days = (window_end - window_start).days + 1
    coverage_ratio = coverage_days / window_days if window_days else 0.0
    coverage_start = min(p.start for p in periods if p.start)
    coverage_end = max(p.end for p in periods)

    ebit_total, ebit_hits = _sum(periods, _ebit_of)
    revenue_total, _ = _sum(periods, lambda v: pick(v, "revenue"))
    ebitda_total, _ = _sum(periods, _ebitda_of)
    pretax_total, _ = _sum(periods, lambda v: pick(v, "pretax_income"))
    tax_total, _ = _sum(periods, lambda v: pick(v, "tax_provision"))

    if ebit_hits < len(periods):
        warnings.append(f"EBIT 결측 기간 {len(periods) - ebit_hits}개")
    if ebit_total is None:
        warnings.append("EBIT을 어떤 기간에서도 찾지 못함")
        empty.coverage_start = coverage_start
        empty.coverage_end = coverage_end
        empty.coverage_days = coverage_days
        empty.coverage_ratio = coverage_ratio
        empty.periods_used = [p.end.isoformat() for p in periods]
        return empty

    # 실효세율
    fallback = params.fallback_tax_rate_by_region.get(region, 0.25)
    if pretax_total and pretax_total > 0 and tax_total is not None:
        raw = abs(tax_total) / pretax_total
        tax_rate = min(max(raw, params.tax_rate_min), params.tax_rate_max)
        tax_source = f"실효 {raw:.1%}"
        if tax_rate != raw:
            tax_source += " (클램프 적용)"
    else:
        tax_rate = fallback
        tax_source = f"{region.upper()} 법정세율 대체"
        warnings.append("실효세율 계산 불가 — 법정세율 사용")

    years = coverage_days / DAYS_PER_YEAR if coverage_days else 0.0
    if years <= 0:
        return empty
    nopat_annualized = ebit_total * (1 - tax_rate) / years
    revenue_annualized = (revenue_total / years) if revenue_total else None

    # 투하자본 스냅샷: 창 직전 기말부터 창 종료 직후까지 전부 평균
    lo = window_start - dt.timedelta(days=400)
    hi = window_end + dt.timedelta(days=45)
    snapshots = [
        p for p in (list(annual_balance) + list(interim_balance)) if lo <= p.end <= hi
    ]
    snapshots.sort(key=lambda p: p.end)
    # 같은 기말이 연간/분기 양쪽에 있으면 하나만 쓴다
    dedup: dict[dt.date, PeriodFacts] = {}
    for p in snapshots:
        dedup.setdefault(p.end, p)
    snapshots = [dedup[k] for k in sorted(dedup)]

    ics = [invested_capital(p.values, revenue_annualized, params) for p in snapshots]
    valid = [ic for ic in ics if ic.value is not None and ic.value > 0]
    if not valid:
        warnings.append("투하자본을 계산할 재무상태표가 없음")
        empty.ebit_total = ebit_total
        empty.revenue_total = revenue_total
        empty.ebitda_total = ebitda_total
        empty.tax_rate = tax_rate
        empty.tax_rate_source = tax_source
        empty.nopat_annualized = nopat_annualized
        empty.coverage_start = coverage_start
        empty.coverage_end = coverage_end
        empty.coverage_days = coverage_days
        empty.coverage_ratio = coverage_ratio
        empty.periods_used = [p.end.isoformat() for p in periods]
        return empty

    ic_avg = sum(ic.value for ic in valid) / len(valid)
    last = valid[-1]

    if len(valid) < 2:
        warnings.append("투하자본 스냅샷 1개 — 기말 단일시점 기준")
    if coverage_ratio < params.min_coverage_ratio:
        warnings.append(f"기간 커버리지 {coverage_ratio:.0%} — 창 구간을 충분히 못 덮음")

    return RoicResult(
        roic=nopat_annualized / ic_avg,
        nopat_annualized=nopat_annualized,
        ebit_total=ebit_total,
        revenue_total=revenue_total,
        ebitda_total=ebitda_total,
        tax_rate=tax_rate,
        tax_rate_source=tax_source,
        invested_capital_avg=ic_avg,
        ic_snapshots=len(valid),
        total_debt_last=last.total_debt,
        equity_last=last.equity,
        excess_cash_last=last.excess_cash,
        goodwill_last=last.goodwill,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        coverage_days=coverage_days,
        coverage_ratio=coverage_ratio,
        periods_used=[f"{p.kind}:{p.end.isoformat()}" for p in periods],
        warnings=warnings,
    )
