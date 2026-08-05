"""유니버스 구성 — "지역 시총 상위 100"을 어떻게 만드는가.

여기에 이 프로젝트의 가장 큰 구조적 한계가 있다.

**무료로 '전 종목 시총 순위'를 주는 API 는 중국(akshare)뿐이다.**
한국/미국/일본/유럽은 전 종목 시총 스냅샷을 무료로 주는 곳이 없어서,
지수 구성종목 같은 시드 리스트를 넣고 그 안에서 시총 정렬해 상위 100을 뽑는다.

따라서 결과의 정확한 의미는
  "시드 리스트 안에서의 시총 상위 100"
이며, 시드에 없는 대형주는 애초에 후보에 들어오지 못한다.
시드 갱신 방법은 seeds/README.md 와 scripts/refresh_seeds.py 를 볼 것.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import REGIONS

log = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parent.parent / "seeds"

# 접미사 → 지역. 긴 접미사를 먼저 검사한다.
SUFFIX_TO_REGION: dict[str, str] = {}
for _code, _region in REGIONS.items():
    for _suffix in _region.exchanges:
        if _suffix:
            SUFFIX_TO_REGION[_suffix] = _code
_SUFFIXES = sorted(SUFFIX_TO_REGION, key=len, reverse=True)


def region_of(ticker: str) -> str:
    """티커 접미사로 지역을 판정한다. 접미사가 없으면 미국."""
    up = ticker.strip().upper()
    for suffix in _SUFFIXES:
        if up.endswith(suffix.upper()):
            return SUFFIX_TO_REGION[suffix]
    return "us"


def exchange_label(ticker: str) -> str:
    up = ticker.strip().upper()
    for suffix in _SUFFIXES:
        if up.endswith(suffix.upper()):
            region = REGIONS[SUFFIX_TO_REGION[suffix]]
            for s, label in region.exchanges.items():
                if s.upper() == suffix.upper():
                    return label
    return REGIONS["us"].exchanges[""]


def load_seeds(region: str, seed_dir: Path | None = None) -> list[str]:
    """seeds/<region>.txt 를 읽는다. '#' 주석과 빈 줄은 무시.

    형식: 한 줄에 `티커` 또는 `티커  # 회사명 메모`
    """
    root = Path(seed_dir) if seed_dir else SEED_DIR
    path = root / f"{region}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"시드 파일이 없습니다: {path}\n"
            f"seeds/README.md 를 참고해 만들거나 --seed-dir 로 경로를 지정하세요."
        )
    tickers: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        tk = line.split()[0]
        if tk.upper() not in seen:
            seen.add(tk.upper())
            tickers.append(tk)
    return tickers


def load_cn_universe_from_akshare(limit: int = 300) -> list[str]:
    """중국만 전 종목 시총 스냅샷이 무료로 나온다 — 진짜 시총 순위를 쓸 수 있다.

    akshare 는 A주 전종목 실시간 시세(f20=총시가)를 한 번에 반환한다.
    실패하면 시드 파일로 조용히 되돌아가도록 예외를 올린다.
    """
    import akshare as ak  # noqa: PLC0415 - 선택적 의존성

    df = ak.stock_zh_a_spot_em()
    col_cap = next((c for c in df.columns if "总市值" in str(c)), None)
    col_code = next((c for c in df.columns if "代码" in str(c)), None)
    if not col_cap or not col_code:
        raise RuntimeError(f"akshare 컬럼 구조가 바뀜: {list(df.columns)[:12]}")

    df = df[[col_code, col_cap]].dropna()
    df = df.sort_values(col_cap, ascending=False).head(limit)

    tickers: list[str] = []
    for code in df[col_code].astype(str):
        code = code.zfill(6)
        # 60/68 = 상하이, 00/30 = 선전
        if code.startswith(("60", "68")):
            tickers.append(f"{code}.SS")
        elif code.startswith(("00", "30")):
            tickers.append(f"{code}.SZ")
    return tickers
