"""지역 정의, ROIC 산식 파라미터, 제외 업종 등 모든 설정을 한 곳에 고정한다.

ROIC 순위가 실행할 때마다 바뀌지 않도록, 정의를 코드가 아니라 여기서 읽는다.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# ROIC 측정 기간
# --------------------------------------------------------------------------
# 사용자 요구: "'24~'26 1H 기준"
# 해석: 2024-01-01 ~ 2026-06-30 구간을 하나의 창(window)으로 보고
#       그 구간의 누적 NOPAT을 연율화한 뒤 같은 구간 평균 투하자본으로 나눈다.
#       일본처럼 회계연도가 4월 시작이면 실제 커버 구간이 어긋나므로
#       결과 시트에 '기간커버' 컬럼으로 실측 구간을 그대로 노출한다.
WINDOW_START = dt.date(2024, 1, 1)
WINDOW_END = dt.date(2026, 6, 30)

DAYS_PER_YEAR = 365.25


@dataclass(frozen=True)
class RoicParams:
    """ROIC 산식 파라미터. 바꾸면 순위가 바뀌므로 결과 파일에 그대로 기록된다."""

    # 실효세율 = 법인세비용 합계 / 세전이익 합계. 아래 범위로 클램프한다.
    # 일회성 세무이슈로 세율이 -50%/+120% 로 튀는 경우가 흔하다.
    tax_rate_min: float = 0.10
    tax_rate_max: float = 0.40
    # 세전이익이 음수이거나 세율 계산이 불가능하면 지역 법정세율로 대체한다.
    fallback_tax_rate_by_region: dict[str, float] = field(
        default_factory=lambda: {
            "kr": 0.24,
            "us": 0.25,
            "jp": 0.30,
            "cn": 0.25,
            "eu": 0.25,
        }
    )
    # 초과현금 = max(0, 현금성자산 - 매출 * operating_cash_pct)
    # 영업에 필요한 최소 현금은 투하자본에 남긴다.
    operating_cash_pct: float = 0.02
    # True 면 투하자본에서 영업권을 뺀다(무기적 성장 제외 관점).
    # 기본은 False = 인수대가도 자본으로 인정하는 정통 ROIC.
    exclude_goodwill: bool = False
    # 투하자본이 이 값보다 작으면 ROIC가 무의미하게 폭발하므로 제외한다.
    min_invested_capital_usd: float = 50_000_000.0
    # 창 구간 커버리지가 이 비율 미만이면(예: 신규상장) 신뢰할 수 없다고 표시한다.
    min_coverage_ratio: float = 0.55


# --------------------------------------------------------------------------
# 지역
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Region:
    code: str
    name: str
    # yfinance 티커 접미사 → 거래소 표시명
    exchanges: dict[str, str]
    # 미래에셋증권 온라인(m.Stock) 매매 가능 여부 — 2026-05 기준 기억, 반드시 재확인 필요
    mirae_online: str
    # 통상 매매단위(주). 종목별로 다를 수 있어 참고값이다.
    typical_lot: str
    note: str = ""


REGIONS: dict[str, Region] = {
    "kr": Region(
        code="kr",
        name="한국",
        exchanges={".KS": "KOSPI", ".KQ": "KOSDAQ"},
        mirae_online="가능",
        typical_lot="1",
    ),
    "us": Region(
        code="us",
        name="미국",
        exchanges={"": "NYSE/NASDAQ"},
        mirae_online="가능",
        typical_lot="1",
        note="ADR 정식상장 포함. OTC(비후원 ADR)는 미래에셋 미지원 가능성 높음",
    ),
    "jp": Region(
        code="jp",
        name="일본",
        exchanges={".T": "TSE"},
        mirae_online="가능",
        typical_lot="100",
        note="매매단위 100주. 고가주는 1회 매수금액이 수천만원",
    ),
    "cn": Region(
        code="cn",
        name="중국",
        exchanges={".SS": "상하이", ".SZ": "선전", ".HK": "홍콩"},
        mirae_online="가능(후강퉁/선강퉁/HKEX)",
        typical_lot="A주 100 / HK 종목별",
        note="A주는 후강퉁·선강퉁 편입종목만. 외국인 보유한도 존재",
    ),
    "eu": Region(
        code="eu",
        name="유럽",
        exchanges={
            ".PA": "Euronext Paris",
            ".AS": "Euronext Amsterdam",
            ".BR": "Euronext Brussels",
            ".LS": "Euronext Lisbon",
            ".DE": "Xetra",
            ".SW": "SIX Swiss",
            ".L": "LSE",
            ".MI": "Borsa Italiana",
            ".MC": "BME Madrid",
            ".ST": "Nasdaq Stockholm",
            ".CO": "Nasdaq Copenhagen",
            ".HE": "Nasdaq Helsinki",
            ".OL": "Oslo Børs",
            ".VI": "Wiener Börse",
            ".IR": "Euronext Dublin",
        },
        mirae_online="온라인 미지원(오프라인 전화주문)",
        typical_lot="1",
        note="거래세: 영국 인지세 0.5%, 프랑스 FTT 0.3%, 아일랜드 1%",
    ),
}

ALL_REGIONS = list(REGIONS)

# 배당 원천징수율(참고값, 조세조약 기준). 실제 적용은 증권사·서류에 따라 다르다.
DIVIDEND_WHT = {
    "kr": "15.4% (국내과세)",
    "us": "15%",
    "jp": "15.315%",
    "cn": "10% (A주) / 10% (H주)",
    "eu": "국가별 0~35% (영 0%, 독 26.375%, 스위스 35%, 프 최대 28%)",
}


# --------------------------------------------------------------------------
# 제외 업종
# --------------------------------------------------------------------------
# 금융/부동산/유틸리티는 투하자본 개념 자체가 성립하지 않거나
# 규제자본 구조 때문에 ROIC 비교가 무의미하다.
EXCLUDED_SECTORS = {
    "financial services",
    "financials",
    "real estate",
    "utilities",
}

# 섹터 분류가 비어 있거나 어긋나는 경우를 잡는 업종명 키워드
EXCLUDED_INDUSTRY_KEYWORDS = (
    "bank",
    "insurance",
    "reinsurance",
    "reit",
    "capital markets",
    "asset management",
    "mortgage",
    "credit services",
    "financial conglomerate",
    "financial data",
    "utilities",
    "electric utilities",
    "gas utilities",
    "water utilities",
    "shell companies",
)


# --------------------------------------------------------------------------
# 스크리닝 기본값
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ScreenParams:
    top_n_marketcap: int = 100  # 지역별 시총 상위 N을 유니버스로
    top_n_roic: int = 30  # 그 안에서 ROIC 상위 N을 최종 선정
    window_start: dt.date = WINDOW_START
    window_end: dt.date = WINDOW_END
    roic: RoicParams = field(default_factory=RoicParams)
