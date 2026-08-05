"""주가 통계 검증 — 특히 액면분할 보정."""

from __future__ import annotations

import datetime as dt

import pytest

from roic_screener.prices import Bar, price_stats, split_adjust


def test_split_adjust_scales_pre_split_prices_down():
    """4:1 분할 후에는 분할 전 종가를 4로 나눠야 같은 축에서 비교된다.

    이걸 빼먹으면 '역대 최고가'가 분할 전 가격이라 현재가와 비교가 무의미해진다.
    """
    bars = [
        Bar(dt.date(2024, 1, 1), 400.0),
        Bar(dt.date(2024, 1, 2), 420.0),
        Bar(dt.date(2024, 1, 3), 110.0, split=4.0),  # 분할 당일부터 분할 후 가격
        Bar(dt.date(2024, 1, 4), 115.0),
    ]
    adj = split_adjust(bars)
    assert [round(b.close, 4) for b in adj] == [100.0, 105.0, 110.0, 115.0]


def test_split_adjust_handles_multiple_splits():
    bars = [
        Bar(dt.date(2020, 1, 1), 800.0),
        Bar(dt.date(2021, 1, 1), 200.0, split=4.0),
        Bar(dt.date(2022, 1, 1), 100.0, split=2.0),
    ]
    adj = split_adjust(bars)
    # 첫 종가는 4×2 = 8 로 나뉜다
    assert adj[0].close == pytest.approx(100.0)
    assert adj[1].close == pytest.approx(100.0)
    assert adj[2].close == pytest.approx(100.0)


def test_split_adjust_ignores_zero_and_one_ratios():
    bars = [Bar(dt.date(2024, 1, 1), 50.0, split=0.0), Bar(dt.date(2024, 1, 2), 51.0, split=1.0)]
    assert [b.close for b in split_adjust(bars)] == [50.0, 51.0]


def test_all_time_high_uses_split_adjusted_series():
    """분할 전 명목 최고가(420)가 아니라 보정 후 최고가가 나와야 한다."""
    bars = [
        Bar(dt.date(2024, 1, 1), 400.0),
        Bar(dt.date(2024, 1, 2), 420.0),
        Bar(dt.date(2024, 1, 3), 110.0, split=4.0),
        Bar(dt.date(2024, 1, 4), 115.0),
    ]
    st = price_stats(bars)
    assert st.high_all == pytest.approx(115.0)
    assert st.high_all_date == dt.date(2024, 1, 4)
    assert st.low_all == pytest.approx(100.0)
    assert st.low_all_date == dt.date(2024, 1, 1)


def test_52w_window_excludes_older_bars():
    """52주 최고가는 최근 365일만 본다. 3년 전 고점은 역대 최고에만 반영된다."""
    bars = (
        [Bar(dt.date(2021, 6, 1) + dt.timedelta(days=i), 500.0) for i in range(10)]
        + [Bar(dt.date(2025, 6, 1) + dt.timedelta(days=i), 100.0 + i) for i in range(200)]
    )
    st = price_stats(bars)
    assert st.high_all == pytest.approx(500.0)
    assert st.high_52w == pytest.approx(299.0)  # 100 + 199
    assert st.low_52w == pytest.approx(100.0)
    assert st.high_52w < st.high_all


def test_pct_of_all_high_reports_price_position():
    bars = [Bar(dt.date(2025, 1, 1) + dt.timedelta(days=i), c)
            for i, c in enumerate([100.0, 200.0, 150.0])]
    st = price_stats(bars)
    assert st.current == pytest.approx(150.0)
    assert st.pct_of_all_high == pytest.approx(0.75)


def test_empty_and_invalid_bars_are_safe():
    assert price_stats([]).current is None
    assert price_stats([Bar(dt.date(2025, 1, 1), 0.0), Bar(dt.date(2025, 1, 2), -5.0)]).current is None


def test_history_start_is_reported_for_reliability_check():
    """역대 최저가의 신뢰도는 히스토리 시작일에 달려 있으므로 함께 노출한다."""
    bars = [Bar(dt.date(2010, 3, 5) + dt.timedelta(days=i), 10.0 + i) for i in range(50)]
    st = price_stats(bars)
    assert st.history_start == dt.date(2010, 3, 5)
    assert st.bars == 50
