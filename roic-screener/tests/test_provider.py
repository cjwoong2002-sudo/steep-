"""프로바이더 계층 검증 — 재시도 정책과 캐시. 네트워크는 타지 않는다."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from roic_screener.provider import (
    DiskCache,
    YFinanceProvider,
    is_permanent_failure,
)


# ---------------------------------------------------------------------------
# 영구 실패 판정
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "message",
    [
        'HTTP Error 404: {"quoteSummary":{"error":{"code":"Not Found",'
        '"description":"Quote not found for symbol: BK"}}}',
        "404 Client Error",
        "MRSH: possibly delisted; no price data found",
        "No data found for this date range",
    ],
)
def test_missing_ticker_is_permanent(message):
    assert is_permanent_failure(RuntimeError(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        "429 Too Many Requests",
        "Failed to perform, curl: (7) CONNECT tunnel failed, response 403",
        "Read timed out",
        "500 Internal Server Error",
    ],
)
def test_transient_errors_are_not_permanent(message):
    assert is_permanent_failure(RuntimeError(message)) is False


# ---------------------------------------------------------------------------
# 재시도 정책
# ---------------------------------------------------------------------------
def _provider(tmp_path, **kw):
    return YFinanceProvider(tmp_path / "cache", min_interval=0.0, **kw)


def test_no_retry_when_ticker_does_not_exist(tmp_path):
    """404 는 재시도해도 절대 성공하지 않는다.

    스테일 티커가 30개면 재시도 3회 + 백오프(1s+2s)로 3분 이상을 그냥 버린다.
    """
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError('HTTP Error 404: Quote not found for symbol: BK')

    p = _provider(tmp_path, max_retries=3)
    with pytest.raises(RuntimeError, match="404"):
        p._retry("BK info", boom)
    assert len(calls) == 1, "404 인데 재시도했다"


def test_retries_transient_errors_up_to_limit(tmp_path):
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("429 Too Many Requests")

    p = _provider(tmp_path, max_retries=3)
    # 백오프 sleep 을 건너뛰기 위해 아주 짧게 만든다
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("roic_screener.provider.time.sleep", lambda _s: None)
        with pytest.raises(RuntimeError, match="429"):
            p._retry("X info", boom)
    assert len(calls) == 3


def test_retry_succeeds_on_second_attempt(tmp_path):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Read timed out")
        return {"marketCap": 123}

    p = _provider(tmp_path, max_retries=3)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("roic_screener.provider.time.sleep", lambda _s: None)
        assert p._retry("X info", flaky) == {"marketCap": 123}
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# 캐시
# ---------------------------------------------------------------------------
def test_cache_roundtrip(tmp_path):
    c = DiskCache(tmp_path, ttl_days=1)
    c.put("co_AAPL", {"info": {"marketCap": 1.0}})
    assert c.get("co_AAPL")["info"]["marketCap"] == 1.0


def test_cache_expires(tmp_path):
    c = DiskCache(tmp_path, ttl_days=1)
    c.put("co_AAPL", {"info": {}})
    stale = json.loads((tmp_path / "co_AAPL.json").read_text(encoding="utf-8"))
    stale["_fetched"] = (dt.datetime.now() - dt.timedelta(days=3)).isoformat(timespec="seconds")
    (tmp_path / "co_AAPL.json").write_text(json.dumps(stale), encoding="utf-8")
    assert c.get("co_AAPL") is None


def test_cache_survives_corrupt_file(tmp_path):
    """캐시가 깨져 있어도 죽지 않고 미스로 처리해 다시 받는다."""
    c = DiskCache(tmp_path, ttl_days=1)
    (tmp_path / "co_AAPL.json").write_text("{ 깨진 json", encoding="utf-8")
    assert c.get("co_AAPL") is None


def test_cache_key_sanitizes_ticker_with_dots(tmp_path):
    """'005930.KS', 'NOVO-B.CO' 같은 티커도 안전한 파일명이 돼야 한다."""
    c = DiskCache(tmp_path, ttl_days=1)
    for ticker in ("005930.KS", "NOVO-B.CO", "0700.HK", "ATCO-A.ST"):
        c.put(f"co_{ticker}", {"info": {"t": ticker}})
        assert c.get(f"co_{ticker}")["info"]["t"] == ticker


def test_cache_miss_returns_none(tmp_path):
    assert DiskCache(tmp_path).get("nope") is None
