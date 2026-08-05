"""스크리닝 제외 규칙.

두 가지 함정을 막는다:
1. 금융·리츠·유틸리티는 투하자본 개념이 성립하지 않아 ROIC 비교가 무의미하다.
2. 자산이 거의 없는 껍데기·로열티 법인은 ROIC 상위를 독식한다
   → 시총 상위 100 필터와 최소 투하자본 조건으로 걸러진다.
"""

from __future__ import annotations

from .config import EXCLUDED_INDUSTRY_KEYWORDS, EXCLUDED_SECTORS


def sector_exclusion_reason(sector: str | None, industry: str | None) -> str | None:
    """제외 사유 문자열, 제외 대상이 아니면 None."""
    s = (sector or "").strip().lower()
    i = (industry or "").strip().lower()

    if s in EXCLUDED_SECTORS:
        return f"제외업종(섹터={sector})"

    for kw in EXCLUDED_INDUSTRY_KEYWORDS:
        if kw in i:
            return f"제외업종(업종={industry})"

    if not s and not i:
        return "업종정보 없음 — 금융 여부 확인 불가"
    return None
