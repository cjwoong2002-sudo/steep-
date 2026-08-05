"""원본 공시 교차검증 소스 (선택).

yfinance 는 비공식 래퍼라 값이 틀릴 수 있다. 상위에 오른 종목만큼은
원본 공시로 확인하는 게 안전하다. 아래 두 모듈이 그 용도다.

    sec.py    미국 — SEC XBRL companyfacts. API 키 불필요, 완전 무료
    dart.py   한국 — DART OpenAPI. 무료지만 API 키 발급 필요

일본(EDINET)·유럽(ESEF)은 회사별 확장 XBRL 태그 매핑 비용이 커서
이 프로젝트 범위에 넣지 않았다. README 의 '검증' 절 참고.
"""
