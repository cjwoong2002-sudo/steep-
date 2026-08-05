"""End-to-end: 가짜 프로바이더로 파이프라인 전체를 돌려 실제 xlsx 를 만들고 다시 읽는다.

네트워크가 막힌 환경에서도 "실행된다"를 증명하는 게 목적이다.
컴파일 통과만으로는 첫 실행에서 죽는 코드를 잡을 수 없다.
"""

from __future__ import annotations

import datetime as dt

import pytest
from conftest import FakeProvider, make_company
from openpyxl import load_workbook

from roic_screener.config import RoicParams, ScreenParams
from roic_screener.excel import write_report
from roic_screener.screener import run_screen

PARAMS = ScreenParams(
    # us 유효 후보 5개(HIGH/BANKX/MID/LOW/TINYCAP) 중 시총 최하위 TINYCAP 을 잘라내는 값.
    # TINYCAP 은 ROIC 가 가장 높게 만들어 뒀다 — 시총 필터가 실제로 먼저 작동하는지 보려고.
    top_n_marketcap=4,
    top_n_roic=3,
    window_start=dt.date(2024, 1, 1),
    window_end=dt.date(2026, 6, 30),
    roic=RoicParams(min_invested_capital_usd=1.0),
)


@pytest.fixture
def world(tmp_path):
    """us 4종목 + kr 3종목. 시드 파일도 tmp_path 에 직접 만든다."""
    companies = {
        # ROIC 는 ebit_scale 로 통제한다 (scale 이 클수록 ROIC 상위)
        "HIGH": make_company("HIGH", name="High ROIC Co", ebit_scale=3.0, market_cap=300e9),
        "MID": make_company("MID", name="Mid ROIC Co", ebit_scale=2.0, market_cap=200e9),
        "LOW": make_company("LOW", name="Low ROIC Co", ebit_scale=1.0, market_cap=100e9),
        "BANKX": make_company(
            "BANKX", name="Big Bank", sector="Financial Services",
            industry="Banks - Diversified", ebit_scale=5.0, market_cap=250e9,
        ),
        "TINYCAP": make_company("TINYCAP", name="Small Co", ebit_scale=9.0, market_cap=1e9),
        "005930.KS": make_company(
            "005930.KS", name="Samsung-ish", currency="KRW",
            market_cap=400e12, ebit_scale=2.5,
        ),
        "000660.KS": make_company(
            "000660.KS", name="Hynix-ish", currency="KRW",
            market_cap=150e12, ebit_scale=1.5,
        ),
        "015760.KS": make_company(
            "015760.KS", name="KEPCO-ish", currency="KRW", market_cap=30e12,
            sector="Utilities", industry="Utilities - Regulated Electric", ebit_scale=4.0,
        ),
    }
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "us.txt").write_text(
        "HIGH\nMID\nLOW\nBANKX\nTINYCAP\nDELISTED\n", encoding="utf-8"
    )
    (seeds / "kr.txt").write_text(
        "005930.KS\n000660.KS\n015760.KS\n", encoding="utf-8"
    )
    provider = FakeProvider(companies, fx={"USDKRW=X": 1350.0})
    return provider, seeds


def test_full_run_produces_expected_ranking(world):
    provider, seeds = world
    res = run_screen(provider, ["us", "kr"], PARAMS, seed_dir=seeds)

    # ROIC 상위 순서: ebit_scale 이 큰 순
    assert [r.ticker for r in res.top["us"]] == ["HIGH", "MID", "LOW"]
    assert [r.ticker for r in res.top["kr"]] == ["005930.KS", "000660.KS"]

    # 금융/유틸리티는 ROIC 가 제일 높아도 제외돼야 한다
    excluded = {r.ticker: r.excluded_reason for r in res.excluded}
    assert "BANKX" in excluded and "제외업종" in excluded["BANKX"]
    assert "015760.KS" in excluded and "제외업종" in excluded["015760.KS"]

    # 시총 하위라 상위 5 유니버스에 못 든 종목은 아예 후보에서 빠진다
    assert "TINYCAP" not in {r.ticker for r in res.top["us"]}
    assert "TINYCAP" not in excluded  # 유니버스 진입 자체를 못 했으므로 제외목록에도 없다

    # 존재하지 않는 티커는 조회실패로 남는다 (예외로 죽지 않는다)
    assert any(e.ticker == "DELISTED" for e in res.errors)


def test_marketcap_ranking_uses_usd_not_local_currency(world):
    """KRW 400조는 USD 로 약 2,963억 달러다. 원화 숫자로 정렬하면 순위가 뒤집힌다."""
    provider, seeds = world
    res = run_screen(provider, ["kr"], PARAMS, seed_dir=seeds)
    ranks = {r.ticker: r.mcap_rank for r in res.universe["kr"]}
    assert ranks["005930.KS"] == 1
    top = res.universe["kr"][0]
    assert top.market_cap_usd == pytest.approx(400e12 / 1350.0)
    assert top.market_cap_usd < top.market_cap  # USD 환산이 실제로 적용됐다


def test_two_pass_fetch_saves_calls(world):
    """업종 제외된 종목과 유니버스 밖 종목은 full fetch 를 하지 않아야 한다."""
    provider, seeds = world
    run_screen(provider, ["us"], PARAMS, seed_dir=seeds)

    assert "TINYCAP" in provider.quote_calls  # 1패스는 전부 조회
    assert "BANKX" in provider.quote_calls
    assert "TINYCAP" not in provider.full_calls  # 유니버스 탈락
    assert "BANKX" not in provider.full_calls  # 업종 제외
    assert set(provider.full_calls) == {"HIGH", "MID", "LOW"}


def test_excel_report_is_written_and_readable(world, tmp_path):
    provider, seeds = world
    res = run_screen(provider, ["us", "kr"], PARAMS, seed_dir=seeds)
    out = write_report(res, tmp_path / "out" / "report.xlsx")

    assert out.exists() and out.stat().st_size > 5000

    wb = load_workbook(out)
    assert wb.sheetnames == [
        "설명",
        "TOP3_통합",
        "US_TOP3",
        "KR_TOP3",
        "계산근거",
        "시총상위4",
        "제외종목",
        "조회실패",
    ]

    ws = wb["TOP3_통합"]
    assert ws["A1"].value == "ROIC순위"
    assert ws.freeze_panes == "D2"
    assert ws.auto_filter.ref is not None

    headers = [c.value for c in ws[1]]
    for required in (
        "ROIC", "EV/EBITDA", "현재가", "52주최고", "52주최저",
        "역대최고", "역대최저", "지역시총순위", "업종(섹터)", "기간커버",
    ):
        assert required in headers, f"요구 컬럼 누락: {required}"

    # 통합 시트는 지역 무관 ROIC 내림차순
    roic_col = headers.index("ROIC") + 1
    values = [ws.cell(row=r, column=roic_col).value for r in range(2, ws.max_row + 1)]
    assert values == sorted(values, reverse=True)
    assert all(isinstance(v, float) for v in values)
    assert ws.cell(row=2, column=roic_col).number_format == "0.0%"


def test_excel_evidence_sheet_carries_calculation_inputs(world, tmp_path):
    """엑셀만 보고도 ROIC 를 재검산할 수 있어야 한다."""
    provider, seeds = world
    res = run_screen(provider, ["us"], PARAMS, seed_dir=seeds)
    out = write_report(res, tmp_path / "r.xlsx")

    ws = load_workbook(out)["계산근거"]
    headers = [c.value for c in ws[1]]
    for required in ("연율화 NOPAT(현지)", "평균 투하자본(현지)", "실효세율",
                     "커버일수", "사용 보고기간", "IC 스냅샷수"):
        assert required in headers

    row = {h: ws.cell(row=2, column=i + 1).value for i, h in enumerate(headers)}
    nopat = row["연율화 NOPAT(현지)"]
    ic = row["평균 투하자본(현지)"]
    roic = row["ROIC"]
    assert nopat / ic == pytest.approx(roic, rel=1e-9)  # 재검산이 맞아떨어진다
    assert row["커버일수"] == 912
    assert row["IC 스냅샷수"] == 5


def test_excel_excluded_sheet_lists_reasons(world, tmp_path):
    provider, seeds = world
    res = run_screen(provider, ["us", "kr"], PARAMS, seed_dir=seeds)
    out = write_report(res, tmp_path / "r.xlsx")

    ws = load_workbook(out)["제외종목"]
    rows = [[c.value for c in row] for row in ws.iter_rows(min_row=2)]
    tickers = {r[1]: r[-1] for r in rows}
    assert "BANKX" in tickers
    assert "제외업종" in tickers["BANKX"]


def test_excel_error_sheet_surfaces_bad_tickers(world, tmp_path):
    provider, seeds = world
    res = run_screen(provider, ["us"], PARAMS, seed_dir=seeds)
    out = write_report(res, tmp_path / "r.xlsx")

    ws = load_workbook(out)["조회실패"]
    tickers = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]
    assert "DELISTED" in tickers


def test_explain_sheet_documents_the_formula(world, tmp_path):
    """산식이 문서화되지 않으면 순위가 매번 바뀌어도 원인을 알 수 없다."""
    provider, seeds = world
    res = run_screen(provider, ["us"], PARAMS, seed_dir=seeds)
    out = write_report(res, tmp_path / "r.xlsx")

    ws = load_workbook(out)["설명"]
    text = "\n".join(
        str(c.value) for row in ws.iter_rows() for c in row if c.value is not None
    )
    assert "ROIC = (Σ EBIT × (1 − 실효세율)" in text
    assert "2024-01-01 ~ 2026-06-30" in text
    assert "금융·부동산(리츠)·유틸리티 제외" in text
    assert "투자자문이 아니다" in text
    assert "시드 리스트 안에서의 시총 상위 100" in text


def test_run_survives_provider_failure_on_full_fetch(tmp_path):
    """2패스에서 특정 종목이 죽어도 전체 실행이 멈추지 않는다."""

    class Flaky(FakeProvider):
        def fetch(self, ticker):
            if ticker == "BROKEN":
                raise RuntimeError("Yahoo 429 Too Many Requests")
            return super().fetch(ticker)

    companies = {
        "OK1": make_company("OK1", ebit_scale=2.0, market_cap=200e9),
        "BROKEN": make_company("BROKEN", ebit_scale=3.0, market_cap=300e9),
    }
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "us.txt").write_text("OK1\nBROKEN\n", encoding="utf-8")

    res = run_screen(Flaky(companies), ["us"], PARAMS, seed_dir=seeds)
    assert [r.ticker for r in res.top["us"]] == ["OK1"]
    assert any(e.ticker == "BROKEN" and "429" in e.message for e in res.errors)
    assert any(r.ticker == "BROKEN" for r in res.excluded)


def test_low_coverage_company_is_excluded_with_reason(tmp_path):
    """상장 직후처럼 창을 못 덮는 기업은 순위에서 빼고 사유를 남긴다."""
    fresh = make_company("IPO", ebit_scale=5.0, market_cap=100e9)
    fresh.annual_income = []
    fresh.interim_income = fresh.interim_income[-1:]  # '26 2분기 하나뿐

    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "us.txt").write_text("IPO\n", encoding="utf-8")

    res = run_screen(FakeProvider({"IPO": fresh}), ["us"], PARAMS, seed_dir=seeds)
    assert res.top["us"] == []
    assert any("커버리지 부족" in (r.excluded_reason or "") for r in res.excluded)


def test_ev_ebitda_computed_when_yahoo_value_missing(tmp_path):
    """Yahoo enterpriseToEbitda 가 없으면 직접 계산하고 출처를 표시한다."""
    c = make_company("NOEV", ebit_scale=1.0, market_cap=100e9, ev_to_ebitda=None)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "us.txt").write_text("NOEV\n", encoding="utf-8")

    res = run_screen(FakeProvider({"NOEV": c}), ["us"], PARAMS, seed_dir=seeds)
    row = res.top["us"][0]
    assert row.ev_to_ebitda is not None
    assert row.ev_to_ebitda > 0
    assert "직접계산" in row.ev_to_ebitda_source
