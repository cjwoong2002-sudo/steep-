"""유니버스·제외 규칙 검증. 시드 파일이 실제로 파싱되는지도 여기서 확인한다."""

from __future__ import annotations

import pytest

from roic_screener.config import ALL_REGIONS
from roic_screener.exclusions import sector_exclusion_reason
from roic_screener.fx import FxRates
from roic_screener.universe import exchange_label, load_seeds, region_of


# ---------------------------------------------------------------------------
# 업종 제외
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "sector,industry",
    [
        ("Financial Services", "Banks - Diversified"),
        ("Real Estate", "REIT - Industrial"),
        ("Utilities", "Utilities - Regulated Electric"),
        ("Technology", "Credit Services"),        # 섹터는 통과하지만 업종에서 걸린다
        ("Industrials", "Insurance - Property"),
    ],
)
def test_financial_real_estate_utilities_excluded(sector, industry):
    assert sector_exclusion_reason(sector, industry) is not None


@pytest.mark.parametrize(
    "sector,industry",
    [
        ("Technology", "Semiconductors"),
        ("Consumer Cyclical", "Luxury Goods"),
        ("Healthcare", "Drug Manufacturers - General"),
        ("Industrials", "Specialty Industrial Machinery"),
    ],
)
def test_normal_sectors_pass(sector, industry):
    assert sector_exclusion_reason(sector, industry) is None


def test_missing_sector_is_excluded_not_silently_passed():
    """업종 정보가 없으면 금융인지 알 수 없으므로 통과시키지 않는다."""
    reason = sector_exclusion_reason(None, None)
    assert reason is not None
    assert "확인 불가" in reason


# ---------------------------------------------------------------------------
# 지역 판정
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "ticker,region",
    [
        ("AAPL", "us"),
        ("BRK-B", "us"),
        ("005930.KS", "kr"),
        ("247540.KQ", "kr"),
        ("7203.T", "jp"),
        ("600519.SS", "cn"),
        ("300750.SZ", "cn"),
        ("0700.HK", "cn"),
        ("MC.PA", "eu"),
        ("ASML.AS", "eu"),
        ("SAP.DE", "eu"),
        ("NESN.SW", "eu"),
        ("AZN.L", "eu"),
        ("RACE.MI", "eu"),
        ("ITX.MC", "eu"),
        ("NOVO-B.CO", "eu"),
        ("ATCO-A.ST", "eu"),
        ("NOKIA.HE", "eu"),
        ("EQNR.OL", "eu"),
        ("OMV.VI", "eu"),
        ("KRZ.IR", "eu"),
    ],
)
def test_region_of_ticker(ticker, region):
    assert region_of(ticker) == region


def test_exchange_label():
    assert exchange_label("005930.KS") == "KOSPI"
    assert exchange_label("0700.HK") == "홍콩"
    assert exchange_label("AAPL") == "NYSE/NASDAQ"


# ---------------------------------------------------------------------------
# 시드 파일
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("region", ALL_REGIONS)
def test_every_seed_file_parses_and_has_enough_candidates(region):
    """상위 100을 뽑으려면 후보가 100보다 많아야 의미가 있다."""
    tickers = load_seeds(region)
    assert len(tickers) >= 100, f"{region}: 후보 {len(tickers)}개 — 상위 100 필터가 무의미"
    assert len(set(t.upper() for t in tickers)) == len(tickers), "중복 티커가 남아 있다"


@pytest.mark.parametrize("region", ALL_REGIONS)
def test_seed_tickers_map_back_to_their_own_region(region):
    """kr.txt 에 .T 가 섞이면 그 종목은 일본으로 분류되어 조용히 빠진다."""
    wrong = [t for t in load_seeds(region) if region_of(t) != region]
    assert not wrong, f"{region}.txt 에 다른 지역 티커: {wrong}"


def test_seed_comments_and_blank_lines_ignored(tmp_path):
    (tmp_path / "xx.txt").write_text(
        "# 주석\n\n  \nAAPL  # Apple\nMSFT\n# 또 주석\nAAPL\n", encoding="utf-8"
    )
    assert load_seeds("xx", tmp_path) == ["AAPL", "MSFT"]


def test_missing_seed_file_gives_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="seeds/README.md"):
        load_seeds("zz", tmp_path)


# ---------------------------------------------------------------------------
# 환율
# ---------------------------------------------------------------------------
def test_fx_direct_pair():
    fx = FxRates(lambda pair: 1.08 if pair == "EURUSD=X" else None)
    assert fx.rate("EUR") == pytest.approx(1.08)
    assert fx.to_usd(100, "EUR") == pytest.approx(108)


def test_fx_inverted_pair():
    """KRW 는 KRWUSD=X 가 없고 USDKRW=X 만 있으므로 역수를 취해야 한다."""
    fx = FxRates(lambda pair: 1350.0 if pair == "USDKRW=X" else None)
    assert fx.rate("KRW") == pytest.approx(1 / 1350.0)
    assert fx.to_usd(1_350_000, "KRW") == pytest.approx(1000)


def test_fx_london_pence_is_one_hundredth_of_pound():
    """LSE 는 펜스 호가 종목이 있다. 100배 틀린 시총으로 랭킹하면 안 된다."""
    fx = FxRates(lambda pair: 1.27 if pair == "GBPUSD=X" else None)
    assert fx.rate("GBp") == pytest.approx(0.0127)


def test_fx_failure_returns_none_not_zero():
    fx = FxRates(lambda pair: None)
    assert fx.rate("XYZ") is None
    assert fx.to_usd(100, "XYZ") is None


def test_fx_usd_is_identity_without_lookup():
    calls = []

    def quote(pair):
        calls.append(pair)
        return None

    fx = FxRates(quote)
    assert fx.rate("USD") == 1.0
    assert calls == []
