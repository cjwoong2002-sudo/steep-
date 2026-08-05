"""테스트 픽스처.

네트워크가 없어도 파이프라인 전체를 실제로 돌릴 수 있도록
`FakeProvider` 로 Yahoo 를 대체한다. 재무 숫자는 손으로 검산 가능한 값을 쓴다.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roic_screener.fields import norm  # noqa: E402
from roic_screener.prices import Bar  # noqa: E402
from roic_screener.provider import CompanyRaw  # noqa: E402
from roic_screener.roic import PeriodFacts  # noqa: E402


def facts(end: str, kind: str = "FY", **accounts) -> PeriodFacts:
    """`facts('2024-12-31', ebit=1000, ...)` → PeriodFacts.

    키워드는 사람이 읽는 이름을 쓰고, 내부에서 Yahoo 라벨로 바꿔 정규화한다.
    이렇게 하면 fields.py 의 별칭 매핑까지 함께 검증된다.
    """
    label_map = {
        "revenue": "Total Revenue",
        "ebit": "Operating Income",
        "ebitda": "EBITDA",
        "pretax": "Pretax Income",
        "tax": "Tax Provision",
        "interest": "Interest Expense",
        "da": "Reconciled Depreciation",
        "debt": "Total Debt",
        "equity": "Total Equity Gross Minority Interest",
        "cash": "Cash Cash Equivalents And Short Term Investments",
        "goodwill": "Goodwill",
        "assets": "Total Assets",
    }
    values = {}
    for key, val in accounts.items():
        if key not in label_map:
            raise KeyError(f"테스트 헬퍼가 모르는 계정: {key}")
        values[norm(label_map[key])] = float(val)
    return PeriodFacts(end=dt.date.fromisoformat(end), values=values, kind=kind)


def bars_from(start: str, days: int, price_fn, splits: dict[str, float] | None = None):
    """일별 종가 시계열 생성. `price_fn(i) -> 종가`."""
    d0 = dt.date.fromisoformat(start)
    splits = {k: v for k, v in (splits or {}).items()}
    out = []
    for i in range(days):
        d = d0 + dt.timedelta(days=i)
        out.append(Bar(d, float(price_fn(i)), splits.get(d.isoformat(), 0.0)))
    return out


# ---------------------------------------------------------------------------
# 손으로 검산할 표준 케이스: 12월 결산 미국 기업
# ---------------------------------------------------------------------------
STANDARD_ANNUAL_INCOME = [
    facts("2023-12-31", revenue=9000, ebit=900, pretax=800, tax=200, ebitda=1200),
    facts("2024-12-31", revenue=10000, ebit=1000, pretax=900, tax=225, ebitda=1350),
    facts("2025-12-31", revenue=11000, ebit=1200, pretax=1100, tax=275, ebitda=1600),
]
STANDARD_INTERIM_INCOME = [
    facts("2025-12-31", "INTERIM", revenue=2900, ebit=320, pretax=300, tax=75, ebitda=420),
    facts("2026-03-31", "INTERIM", revenue=2800, ebit=300, pretax=280, tax=70, ebitda=400),
    facts("2026-06-30", "INTERIM", revenue=2900, ebit=320, pretax=300, tax=75, ebitda=420),
]
STANDARD_BALANCE = [
    facts("2023-12-31", debt=2000, equity=6000, cash=1000, goodwill=500, assets=12000),
    facts("2024-12-31", debt=2000, equity=6000, cash=1000, goodwill=500, assets=12000),
    facts("2025-12-31", debt=2000, equity=6000, cash=1000, goodwill=500, assets=12000),
]
STANDARD_INTERIM_BALANCE = [
    facts("2026-03-31", "INTERIM", debt=2000, equity=6000, cash=1000, goodwill=500),
    facts("2026-06-30", "INTERIM", debt=2000, equity=6000, cash=1000, goodwill=500),
]


class FakeProvider:
    """Provider 프로토콜의 인메모리 구현. 호출 횟수도 세어 2패스 동작을 검증한다."""

    def __init__(self, companies: dict[str, CompanyRaw], fx: dict[str, float] | None = None):
        self.companies = companies
        self.fx = fx or {"USD=X": 1.0}
        self.quote_calls: list[str] = []
        self.full_calls: list[str] = []

    def fetch_quote(self, ticker: str) -> CompanyRaw:
        self.quote_calls.append(ticker)
        if ticker not in self.companies:
            raise RuntimeError(f"404 Not Found: {ticker}")
        c = self.companies[ticker]
        return CompanyRaw(
            ticker=c.ticker,
            name=c.name,
            sector=c.sector,
            industry=c.industry,
            currency=c.currency,
            exchange=c.exchange,
            market_cap=c.market_cap,
            ev_to_ebitda=c.ev_to_ebitda,
            enterprise_value=c.enterprise_value,
        )

    def fetch(self, ticker: str) -> CompanyRaw:
        self.full_calls.append(ticker)
        if ticker not in self.companies:
            raise RuntimeError(f"404 Not Found: {ticker}")
        return self.companies[ticker]

    def fx_quote(self, pair: str) -> float | None:
        return self.fx.get(pair)


def make_company(
    ticker: str,
    *,
    name: str | None = None,
    sector: str = "Technology",
    industry: str = "Software - Infrastructure",
    currency: str = "USD",
    market_cap: float = 50e9,
    ebit_scale: float = 1.0,
    ev_to_ebitda: float | None = 20.0,
    debt: float = 2000,
    equity: float = 6000,
    cash: float = 1000,
) -> CompanyRaw:
    """표준 케이스를 배수로 변형해 ROIC 순서를 통제한다."""
    ai = [
        facts(
            p.end.isoformat(),
            revenue=p.values[norm("Total Revenue")],
            ebit=p.values[norm("Operating Income")] * ebit_scale,
            pretax=p.values[norm("Pretax Income")],
            tax=p.values[norm("Tax Provision")],
            ebitda=p.values[norm("EBITDA")],
        )
        for p in STANDARD_ANNUAL_INCOME
    ]
    ii = [
        facts(
            p.end.isoformat(),
            "INTERIM",
            revenue=p.values[norm("Total Revenue")],
            ebit=p.values[norm("Operating Income")] * ebit_scale,
            pretax=p.values[norm("Pretax Income")],
            tax=p.values[norm("Tax Provision")],
            ebitda=p.values[norm("EBITDA")],
        )
        for p in STANDARD_INTERIM_INCOME
    ]
    ab = [facts(p.end.isoformat(), debt=debt, equity=equity, cash=cash, goodwill=500)
          for p in STANDARD_BALANCE]
    ib = [facts(p.end.isoformat(), "INTERIM", debt=debt, equity=equity, cash=cash, goodwill=500)
          for p in STANDARD_INTERIM_BALANCE]

    return CompanyRaw(
        ticker=ticker,
        name=name or f"{ticker} Inc.",
        sector=sector,
        industry=industry,
        currency=currency,
        exchange="Test Exchange",
        market_cap=market_cap,
        ev_to_ebitda=ev_to_ebitda,
        enterprise_value=market_cap * 1.1,
        annual_income=ai,
        interim_income=ii,
        annual_balance=ab,
        interim_balance=ib,
        bars=bars_from("2020-01-01", 2400, lambda i: 100 + i * 0.05),
    )


@pytest.fixture
def standard_company() -> CompanyRaw:
    return make_company("TEST")
