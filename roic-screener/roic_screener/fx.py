"""통화 환산.

지역별 시총 상위 100을 뽑으려면 유럽처럼 여러 통화가 섞인 지역은
USD 로 환산해야 순위가 성립한다.

Yahoo 는 통화쌍 티커가 두 방향으로 존재한다:
  EURUSD=X  → 1 EUR 이 몇 USD (직접 계수)
  KRW=X     → 1 USD 가 몇 KRW (역수 필요)
둘 다 시도하고, 실패하면 환산 불가로 표시한다(0으로 채우지 않는다).
"""

from __future__ import annotations

from typing import Callable

# 통화 → 소수 단위 없음 여부 등 표시용 메타
CURRENCY_NAMES = {
    "USD": "미국 달러",
    "KRW": "원",
    "JPY": "엔",
    "CNY": "위안",
    "HKD": "홍콩 달러",
    "EUR": "유로",
    "GBP": "영국 파운드",
    "GBp": "영국 펜스",
    "CHF": "스위스 프랑",
    "SEK": "스웨덴 크로나",
    "DKK": "덴마크 크로네",
    "NOK": "노르웨이 크로네",
}


class FxRates:
    """USD 환산 계수를 캐시한다. rate(cur) = 1단위 cur 당 USD."""

    def __init__(self, quote_fn: Callable[[str], float | None]):
        self._quote = quote_fn
        self._cache: dict[str, float | None] = {"USD": 1.0}

    def rate(self, currency: str | None) -> float | None:
        if not currency:
            return None
        cur = currency.strip()
        # LSE 는 펜스(GBp) 로 호가하는 종목이 있다. 100분의 1 파운드.
        if cur == "GBp":
            gbp = self.rate("GBP")
            return gbp / 100.0 if gbp else None
        cur = cur.upper()
        if cur in self._cache:
            return self._cache[cur]

        rate = self._quote(f"{cur}USD=X")
        if not rate:
            inv = self._quote(f"USD{cur}=X") or self._quote(f"{cur}=X")
            rate = (1.0 / inv) if inv else None
        self._cache[cur] = rate
        return rate

    def to_usd(self, amount: float | None, currency: str | None) -> float | None:
        if amount is None:
            return None
        r = self.rate(currency)
        return amount * r if r else None

    def snapshot(self) -> dict[str, float | None]:
        return dict(self._cache)
