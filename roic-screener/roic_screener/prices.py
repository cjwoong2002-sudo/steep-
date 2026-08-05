"""주가 시계열 가공 — 순수 함수.

역대 최고/최저가는 액면분할 보정을 하지 않으면 무의미하다.
반대로 배당까지 보정한 수정주가(Adj Close)를 쓰면 "역대 최고가"가
실제로 그 가격에 거래된 적 없는 숫자가 된다.

그래서 여기서는 **분할만 보정한** 시계열을 만들어 쓴다.
(배당 재투자 수익률을 보는 게 목적이 아니므로 이게 맞다)

한계: Yahoo 히스토리는 오래된 상장사의 1980년대 이전 데이터가 없거나
증자·감자 보정이 누락된 경우가 있다. 그래서 '역대최저가' 기준일도 함께 출력해
사용자가 신뢰도를 직접 판단할 수 있게 한다.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass
class Bar:
    date: dt.date
    close: float
    split: float = 0.0  # 해당일에 적용된 분할비율 (0 또는 1 = 분할 없음)


@dataclass
class PriceStats:
    current: float | None = None
    current_date: dt.date | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    high_all: float | None = None
    high_all_date: dt.date | None = None
    low_all: float | None = None
    low_all_date: dt.date | None = None
    history_start: dt.date | None = None
    bars: int = 0
    # 현재가가 역대 최고가 대비 몇 %인지 — "가격 위치" 판단용
    pct_of_all_high: float | None = None
    pct_of_52w_high: float | None = None


def split_adjust(bars: list[Bar]) -> list[Bar]:
    """분할만 보정한 종가 시계열을 만든다(최신 가격 기준으로 과거를 환산)."""
    ordered = sorted(bars, key=lambda b: b.date)
    factor = 1.0
    out: list[Bar] = []
    for b in reversed(ordered):
        out.append(Bar(date=b.date, close=b.close / factor, split=b.split))
        if b.split and b.split > 0 and b.split != 1.0:
            factor *= b.split
    out.reverse()
    return out


def price_stats(bars: list[Bar], *, asof: dt.date | None = None) -> PriceStats:
    clean = [b for b in bars if b.close is not None and b.close > 0]
    if not clean:
        return PriceStats()

    adj = split_adjust(clean)
    asof = asof or adj[-1].date
    cutoff = asof - dt.timedelta(days=365)

    last = adj[-1]
    window = [b for b in adj if b.date >= cutoff] or [last]

    hi_all = max(adj, key=lambda b: b.close)
    lo_all = min(adj, key=lambda b: b.close)

    st = PriceStats(
        current=last.close,
        current_date=last.date,
        high_52w=max(b.close for b in window),
        low_52w=min(b.close for b in window),
        high_all=hi_all.close,
        high_all_date=hi_all.date,
        low_all=lo_all.close,
        low_all_date=lo_all.date,
        history_start=adj[0].date,
        bars=len(adj),
    )
    if st.high_all:
        st.pct_of_all_high = st.current / st.high_all
    if st.high_52w:
        st.pct_of_52w_high = st.current / st.high_52w
    return st
