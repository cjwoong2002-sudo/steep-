"""재무제표 계정 이름 매핑.

yfinance(=Yahoo)는 계정 라벨을 예고 없이 바꾸고, 회사·회계기준(IFRS/US-GAAP/J-GAAP/CAS)
마다 있는 계정이 다르다. 그래서 어디서도 "정확한 이름"을 가정하지 않고
별칭 목록 → 정규화 비교 → 키워드 부분일치 순서로 관용적으로 찾는다.

계정을 하나도 못 찾으면 조용히 0으로 두지 않고 None을 반환한다.
조용한 0은 ROIC를 그럴듯하게 틀리게 만든다.
"""

from __future__ import annotations

import re

_NORM = re.compile(r"[^a-z0-9]+")


def norm(label: str) -> str:
    return _NORM.sub("", str(label).lower())


# 별칭은 우선순위 순서다. 앞에 있는 것이 먼저 채택된다.
ALIASES: dict[str, tuple[str, ...]] = {
    # ---- 손익계산서 ----
    "revenue": (
        "Total Revenue",
        "Operating Revenue",
        "Revenue",
        "Net Sales",
    ),
    "ebit": (
        "EBIT",
        "Operating Income",
        "Total Operating Income As Reported",
        "Operating Income Loss",
    ),
    "ebitda": (
        "EBITDA",
        "Normalized EBITDA",
    ),
    "pretax_income": (
        "Pretax Income",
        "Income Before Tax",
        "Income Loss From Continuing Operations Before Income Taxes",
    ),
    "tax_provision": (
        "Tax Provision",
        "Income Tax Expense Benefit",
        "Provision For Income Taxes",
    ),
    "net_income": (
        "Net Income",
        "Net Income Common Stockholders",
        "Net Income Including Noncontrolling Interests",
    ),
    "interest_expense": (
        "Interest Expense",
        "Interest Expense Non Operating",
        "Net Interest Income",
    ),
    "depreciation_amortization": (
        "Reconciled Depreciation",
        "Depreciation And Amortization",
        "Depreciation Amortization Depletion",
    ),
    # ---- 재무상태표 ----
    "total_debt": (
        "Total Debt",
        "Total Debt And Capital Lease Obligation",
    ),
    "long_term_debt": (
        "Long Term Debt And Capital Lease Obligation",
        "Long Term Debt",
    ),
    "current_debt": (
        "Current Debt And Capital Lease Obligation",
        "Current Debt",
        "Short Long Term Debt",
    ),
    "equity_incl_minority": (
        "Total Equity Gross Minority Interest",
        "Total Equity",
    ),
    "stockholders_equity": (
        "Stockholders Equity",
        "Total Stockholder Equity",
        "Common Stock Equity",
    ),
    "minority_interest": (
        "Minority Interest",
        "Noncontrolling Interest",
    ),
    "cash_and_sti": (
        "Cash Cash Equivalents And Short Term Investments",
        "Cash And Cash Equivalents",
        "Cash Financial",
        "Cash",
    ),
    "short_term_investments": (
        "Other Short Term Investments",
        "Short Term Investments",
    ),
    "goodwill": (
        "Goodwill",
        "Goodwill And Other Intangible Assets",
    ),
    "total_assets": ("Total Assets",),
    "current_liabilities": (
        "Current Liabilities",
        "Total Current Liabilities",
    ),
}

# 별칭이 전부 실패했을 때 마지막으로 시도하는 부분일치 키워드
FUZZY: dict[str, tuple[str, ...]] = {
    "revenue": ("totalrevenue", "revenue", "sales"),
    "ebit": ("ebit", "operatingincome"),
    "ebitda": ("ebitda",),
    "pretax_income": ("pretax", "beforetax", "beforeincometax"),
    "tax_provision": ("taxprovision", "incometax"),
    "total_debt": ("totaldebt",),
    "equity_incl_minority": ("totalequity",),
    "stockholders_equity": ("stockholdersequity", "shareholdersequity"),
    "minority_interest": ("minorityinterest", "noncontrolling"),
    "cash_and_sti": ("cashcashequivalents", "cashandcashequivalents"),
    "goodwill": ("goodwill",),
    "total_assets": ("totalassets",),
}


def pick(values: dict[str, float], key: str) -> float | None:
    """정규화된 계정 dict 에서 논리적 계정 `key` 값을 찾는다. 없으면 None."""
    if key not in ALIASES:
        raise KeyError(f"unknown logical field: {key}")

    for alias in ALIASES[key]:
        v = values.get(norm(alias))
        if v is not None:
            return v

    for kw in FUZZY.get(key, ()):
        # 짧은 키워드가 엉뚱한 계정에 걸리지 않도록 후보를 모아 가장 짧은 이름을 쓴다
        hits = [(k, v) for k, v in values.items() if kw in k and v is not None]
        if hits:
            hits.sort(key=lambda kv: len(kv[0]))
            return hits[0][1]
    return None


def normalize_values(raw: dict) -> dict[str, float]:
    """{원본 라벨: 값} → {정규화 라벨: float}. NaN/None 은 버린다."""
    out: dict[str, float] = {}
    for label, val in raw.items():
        if val is None:
            continue
        try:
            f = float(val)
        except (TypeError, ValueError):
            continue
        if f != f:  # NaN
            continue
        out[norm(label)] = f
    return out
