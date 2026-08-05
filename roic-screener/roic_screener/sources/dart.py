"""한국 — DART OpenAPI 교차검증.

무료지만 API 키가 필요하다: https://opendart.fss.or.kr → 인증키 신청 (이메일 인증)
환경변수 `DART_API_KEY` 로 넘긴다.

pykrx 는 2026년부터 KRX 로그인(KRX_ID/KRX_PW)을 요구해 무인증 스크래핑이 막혔다.
그래서 시총·주가는 yfinance(.KS/.KQ)로 받고, 재무 원본만 DART 로 확인한다.

사용:
    from roic_screener.sources.dart import DartClient
    c = DartClient()                       # DART_API_KEY 환경변수 사용
    corp = c.corp_code("005930")           # 종목코드 → 고유번호
    fs = c.financials(corp, 2025, "11011") # 11011=사업보고서, 11012=반기
"""

from __future__ import annotations

import io
import json
import logging
import os
import urllib.parse
import urllib.request
import zipfile
from xml.etree import ElementTree

log = logging.getLogger(__name__)

BASE = "https://opendart.fss.or.kr/api"

# 보고서 코드
REPORT_ANNUAL = "11011"  # 사업보고서
REPORT_H1 = "11012"  # 반기보고서
REPORT_Q1 = "11013"
REPORT_Q3 = "11014"


class DartClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("DART_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "DART API 키가 없습니다. https://opendart.fss.or.kr 에서 발급 후 "
                "환경변수 DART_API_KEY 에 설정하세요."
            )
        self._corp_codes: dict[str, str] | None = None

    def _get(self, path: str, **params) -> bytes:
        params["crtfc_key"] = self.api_key
        url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
            return resp.read()

    def corp_code(self, stock_code: str) -> str | None:
        """종목코드(6자리) → DART 고유번호(8자리). 전체 목록 zip 을 한 번만 받는다."""
        if self._corp_codes is None:
            blob = self._get("corpCode.xml")
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                xml = zf.read(zf.namelist()[0])
            root = ElementTree.fromstring(xml)
            table: dict[str, str] = {}
            for node in root.iter("list"):
                stock = (node.findtext("stock_code") or "").strip()
                corp = (node.findtext("corp_code") or "").strip()
                if stock and corp:
                    table[stock] = corp
            self._corp_codes = table
            log.info("DART 고유번호 %d건 로드", len(table))
        return self._corp_codes.get(stock_code.split(".")[0])

    def financials(self, corp_code: str, year: int, report_code: str = REPORT_ANNUAL) -> list[dict]:
        """전체 재무제표(fnlttSinglAcntAll). 연결(CFS) 우선, 없으면 별도(OFS)."""
        for fs_div in ("CFS", "OFS"):
            raw = self._get(
                "fnlttSinglAcntAll.json",
                corp_code=corp_code,
                bsns_year=str(year),
                reprt_code=report_code,
                fs_div=fs_div,
            )
            data = json.loads(raw)
            if data.get("status") == "000" and data.get("list"):
                return data["list"]
            if data.get("status") not in ("013", "000"):  # 013 = 조회 데이터 없음
                log.warning("DART %s %s: status=%s %s", corp_code, fs_div,
                            data.get("status"), data.get("message"))
        return []

    @staticmethod
    def find_account(rows: list[dict], *keywords: str) -> float | None:
        """계정명 부분일치로 당기 금액을 찾는다.

        한국 공시는 계정명이 회사마다 다르다('영업이익', '영업이익(손실)' 등).
        그래서 정확 일치를 기대하지 않는다.
        """
        for row in rows:
            name = (row.get("account_nm") or "").replace(" ", "")
            if all(kw.replace(" ", "") in name for kw in keywords):
                val = (row.get("thstrm_amount") or "").replace(",", "")
                try:
                    return float(val)
                except ValueError:
                    continue
        return None
