"""ROIC 엔진 검증 — 손으로 검산한 값과 대조한다."""

from __future__ import annotations

import datetime as dt

import pytest
from conftest import (
    STANDARD_ANNUAL_INCOME,
    STANDARD_BALANCE,
    STANDARD_INTERIM_BALANCE,
    STANDARD_INTERIM_INCOME,
    facts,
)

from roic_screener.config import DAYS_PER_YEAR, RoicParams
from roic_screener.roic import compute_roic, infer_starts, invested_capital, select_window_periods

W_START = dt.date(2024, 1, 1)
W_END = dt.date(2026, 6, 30)
PARAMS = RoicParams()


def run(annual=None, interim=None, ab=None, ib=None, region="us", params=PARAMS,
        start=W_START, end=W_END):
    return compute_roic(
        annual_income=annual if annual is not None else STANDARD_ANNUAL_INCOME,
        interim_income=interim if interim is not None else STANDARD_INTERIM_INCOME,
        annual_balance=ab if ab is not None else STANDARD_BALANCE,
        interim_balance=ib if ib is not None else STANDARD_INTERIM_BALANCE,
        window_start=start,
        window_end=end,
        region=region,
        params=params,
    )


# ---------------------------------------------------------------------------
def test_window_covers_exactly_24_to_26h1():
    """'24-01-01 ~ '26-06-30 은 912일. 12월 결산 기업이면 100% 커버되어야 한다."""
    res = run()
    assert res.coverage_start == dt.date(2024, 1, 1)
    assert res.coverage_end == dt.date(2026, 6, 30)
    assert res.coverage_days == 912
    assert res.coverage_ratio == pytest.approx(1.0)
    # FY23 은 창 밖이므로 쓰이지 않아야 한다
    assert "FY:2023-12-31" not in res.periods_used
    assert res.periods_used == [
        "FY:2024-12-31",
        "FY:2025-12-31",
        "INTERIM:2026-03-31",
        "INTERIM:2026-06-30",
    ]


def test_roic_matches_hand_calculation():
    """손 검산:
        EBIT 합 = 1000 + 1200 + 300 + 320        = 2820
        세전 합 = 900 + 1100 + 280 + 300         = 2580
        세금 합 = 225 + 275 + 70 + 75            = 645
        실효세율 = 645 / 2580                     = 0.25 (클램프 범위 내)
        커버연수 = 912 / 365.25
        연율화 NOPAT = 2820 × 0.75 ÷ 커버연수
        매출 합 = 10000 + 11000 + 2800 + 2900     = 26700
        연율화 매출 = 26700 ÷ 커버연수
        초과현금 = 1000 − 연율화매출 × 2%
        IC = 2000 + 6000 − 초과현금  (5개 스냅샷 모두 동일)
    """
    res = run()
    years = 912 / DAYS_PER_YEAR

    assert res.ebit_total == pytest.approx(2820)
    assert res.revenue_total == pytest.approx(26700)
    assert res.tax_rate == pytest.approx(0.25)
    assert res.tax_rate_source == "실효 25.0%"

    expected_nopat = 2820 * 0.75 / years
    assert res.nopat_annualized == pytest.approx(expected_nopat)

    revenue_ann = 26700 / years
    expected_ic = 2000 + 6000 - (1000 - revenue_ann * 0.02)
    assert res.invested_capital_avg == pytest.approx(expected_ic)
    assert res.ic_snapshots == 5

    assert res.roic == pytest.approx(expected_nopat / expected_ic)
    # 회귀 방지용 절대값 고정 (산식이 조용히 바뀌면 여기서 깨진다)
    assert res.roic == pytest.approx(0.11742, abs=1e-5)
    assert res.warnings == []


def test_goodwill_exclusion_raises_roic():
    """영업권을 투하자본에서 빼면 분모가 줄어 ROIC 가 올라간다."""
    base = run()
    ex = run(params=RoicParams(exclude_goodwill=True))
    assert ex.invested_capital_avg == pytest.approx(base.invested_capital_avg - 500)
    assert ex.roic > base.roic


def test_tax_rate_clamped_high():
    """일회성 세무이슈로 실효세율이 80% 로 튀어도 40% 로 잘린다."""
    annual = [
        facts("2023-12-31", revenue=9000, ebit=900, pretax=800, tax=200),
        facts("2024-12-31", revenue=10000, ebit=1000, pretax=1000, tax=800),
        facts("2025-12-31", revenue=11000, ebit=1200, pretax=1000, tax=800),
    ]
    res = run(annual=annual, interim=[])
    assert res.tax_rate == pytest.approx(0.40)
    assert "클램프" in res.tax_rate_source


def test_tax_rate_falls_back_when_pretax_negative():
    """세전이익이 적자면 실효세율이 무의미하므로 지역 법정세율을 쓴다."""
    annual = [
        facts("2023-12-31", revenue=9000, ebit=900, pretax=-800, tax=50),
        facts("2024-12-31", revenue=10000, ebit=1000, pretax=-900, tax=50),
        facts("2025-12-31", revenue=11000, ebit=1200, pretax=-500, tax=50),
    ]
    res = run(annual=annual, interim=[], region="jp")
    assert res.tax_rate == pytest.approx(0.30)  # jp 법정세율
    assert "법정세율" in res.tax_rate_source
    assert any("실효세율 계산 불가" in w for w in res.warnings)


def test_japanese_march_fiscal_year_alignment():
    """3월 결산이면 창과 어긋난다 — 커버 구간이 '24-04-01 부터로 밀리고 커버율이 떨어진다.

    이게 조용히 넘어가면 일본 기업과 미국 기업의 ROIC 를 다른 기간으로 비교하게 된다.
    """
    annual = [
        facts("2024-03-31", revenue=9000, ebit=900, pretax=800, tax=200),
        facts("2025-03-31", revenue=10000, ebit=1000, pretax=900, tax=225),
        facts("2026-03-31", revenue=11000, ebit=1200, pretax=1100, tax=275),
    ]
    interim = [facts("2026-06-30", "INTERIM", revenue=2800, ebit=300, pretax=280, tax=70)]
    balance = [
        facts("2025-03-31", debt=2000, equity=6000, cash=1000),
        facts("2026-03-31", debt=2000, equity=6000, cash=1000),
    ]
    res = run(annual=annual, interim=interim, ab=balance, ib=[], region="jp")

    assert res.coverage_start == dt.date(2024, 4, 1)
    assert res.coverage_end == dt.date(2026, 6, 30)
    # FY 365 + FY 365 + 분기 91 = 821일, 창 912일 → 90%
    assert res.coverage_days == 821
    assert res.coverage_ratio == pytest.approx(821 / 912, abs=1e-4)
    # '23-04 ~ '24-03 회계연도는 창 밖이라 제외됐어야 한다
    assert "FY:2024-03-31" not in res.periods_used


def test_semiannual_reporter_without_h1_2026():
    """유럽 반기보고 기업이 '26 1H 를 아직 안 냈으면 커버 구간이 '25 말까지로 줄어든다."""
    annual = [
        facts("2023-12-31", revenue=9000, ebit=900, pretax=800, tax=200),
        facts("2024-12-31", revenue=10000, ebit=1000, pretax=900, tax=225),
        facts("2025-12-31", revenue=11000, ebit=1200, pretax=1100, tax=275),
    ]
    res = run(annual=annual, interim=[])
    assert res.coverage_end == dt.date(2025, 12, 31)
    assert res.coverage_days == 731  # 366 + 365
    assert res.coverage_ratio == pytest.approx(731 / 912, abs=1e-4)
    assert res.roic is not None  # 커버율 80% 는 여전히 계산 가능


def test_no_overlapping_periods_double_counted():
    """FY2025 와 그 4분기가 둘 다 있어도 4분기를 중복 가산하지 않는다."""
    res = run()
    # 2025-12-31 로 끝나는 INTERIM 은 FY2025 안에 들어 있으므로 제외돼야 한다
    assert "INTERIM:2025-12-31" not in res.periods_used
    assert res.ebit_total == pytest.approx(2820)


def test_ebit_falls_back_to_pretax_plus_interest():
    """영업이익 계정이 없으면 세전이익 + 이자비용으로 근사한다."""
    annual = [
        facts("2023-12-31", revenue=9000, pretax=800, tax=200, interest=100),
        facts("2024-12-31", revenue=10000, pretax=900, tax=225, interest=100),
        facts("2025-12-31", revenue=11000, pretax=1100, tax=275, interest=150),
    ]
    res = run(annual=annual, interim=[])
    assert res.ebit_total == pytest.approx((900 + 100) + (1100 + 150))


def test_missing_balance_sheet_returns_no_roic_not_zero():
    """재무상태표가 없으면 ROIC 를 0 이나 무한대로 만들지 않고 None 을 준다."""
    res = run(ab=[], ib=[])
    assert res.roic is None
    assert res.ok is False
    assert any("투하자본" in w for w in res.warnings)
    # 그래도 손익 쪽 정보는 살려서 진단에 쓸 수 있게 남긴다
    assert res.ebit_total == pytest.approx(2820)


def test_missing_income_returns_no_roic():
    res = run(annual=[], interim=[])
    assert res.roic is None
    assert res.coverage_days == 0


def test_only_interim_data_still_works():
    """연간보고가 창 안에 없고 분기만 있어도 계산은 되고 경고가 남는다."""
    interim = [
        facts("2025-12-31", "INTERIM", revenue=2900, ebit=320, pretax=300, tax=75),
        facts("2026-03-31", "INTERIM", revenue=2800, ebit=300, pretax=280, tax=70),
        facts("2026-06-30", "INTERIM", revenue=2900, ebit=320, pretax=300, tax=75),
    ]
    res = run(annual=[], interim=interim)
    assert res.roic is not None
    assert any("연간보고" in w for w in res.warnings)
    assert res.coverage_ratio < 0.35


# ---------------------------------------------------------------------------
def test_infer_starts_chains_from_previous_period_end():
    ps = infer_starts([facts("2025-12-31"), facts("2024-12-31"), facts("2023-12-31")])
    assert [p.start for p in ps] == [
        dt.date(2023, 1, 1),  # 직전 기말이 없어 365일 역산
        dt.date(2024, 1, 1),
        dt.date(2025, 1, 1),
    ]


def test_infer_starts_caps_absurd_gap_for_interim():
    """분기 사이에 데이터가 빠져 간격이 400일이면 그대로 믿지 않고 1분기로 자른다."""
    ps = infer_starts([
        facts("2024-06-30", "INTERIM"),
        facts("2025-09-30", "INTERIM"),
    ])
    assert ps[1].days <= 95


def test_select_window_periods_empty_input():
    chosen, warns = select_window_periods([], [], W_START, W_END)
    assert chosen == []
    assert warns


def test_invested_capital_does_not_double_count_short_term_investments():
    """'현금+단기금융상품' 합계 계정이 있으면 단기투자를 다시 더하지 않는다."""
    from roic_screener.fields import norm

    bs = {
        norm("Total Debt"): 1000.0,
        norm("Total Equity Gross Minority Interest"): 5000.0,
        norm("Cash Cash Equivalents And Short Term Investments"): 800.0,
        norm("Other Short Term Investments"): 300.0,  # 위 합계에 이미 포함
    }
    ic = invested_capital(bs, revenue_annualized=10000, params=PARAMS)
    # 초과현금 = 800 - 200 = 600  →  IC = 1000 + 5000 - 600 = 5400
    assert ic.excess_cash == pytest.approx(600)
    assert ic.value == pytest.approx(5400)


def test_invested_capital_sums_cash_when_no_combined_account():
    from roic_screener.fields import norm

    bs = {
        norm("Total Debt"): 1000.0,
        norm("Stockholders Equity"): 4000.0,
        norm("Minority Interest"): 1000.0,
        norm("Cash And Cash Equivalents"): 500.0,
        norm("Other Short Term Investments"): 300.0,
    }
    ic = invested_capital(bs, revenue_annualized=10000, params=PARAMS)
    assert ic.equity == pytest.approx(5000)  # 비지배지분 포함
    assert ic.excess_cash == pytest.approx(800 - 200)
    assert ic.value == pytest.approx(1000 + 5000 - 600)


def test_excess_cash_never_negative():
    """현금이 영업필요현금보다 적으면 초과현금은 0이다(투하자본을 부풀리지 않는다)."""
    from roic_screener.fields import norm

    bs = {
        norm("Total Debt"): 1000.0,
        norm("Total Equity Gross Minority Interest"): 5000.0,
        norm("Cash Cash Equivalents And Short Term Investments"): 50.0,
    }
    ic = invested_capital(bs, revenue_annualized=100000, params=PARAMS)
    assert ic.excess_cash == 0.0
    assert ic.value == pytest.approx(6000)
