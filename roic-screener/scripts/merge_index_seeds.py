#!/usr/bin/env python3
"""공개 지수 구성종목을 시드 파일에 병합한다.

`pytickersymbols` (PyPI) 는 주요 지수 구성종목을 **오프라인 번들 JSON** 으로 들고 있다.
네트워크가 막힌 환경에서도 실제 티커를 확보할 수 있는 유일한 경로였다.

**교체가 아니라 병합이다.** pytickersymbols 가 커버하지 못하는 거래소가 있기 때문이다:
  - 덴마크(.CO) — 노보노디스크가 여기 있다. OMX 코펜하겐 지수가 없다
  - 노르웨이(.OL), 이탈리아(.MI), 포르투갈(.LS), 아일랜드(.IR), 오스트리아(.VI)
  - 한국(.KS/.KQ), 중국(.SS/.SZ/.HK) — 아예 커버 안 됨
이 거래소들은 기존 수기 목록을 유지해야 한다.

    python scripts/merge_index_seeds.py --dry-run
    python scripts/merge_index_seeds.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEEDS = ROOT / "seeds"
sys.path.insert(0, str(ROOT))

from roic_screener.universe import load_seeds, region_of  # noqa: E402

# 지역 → 가져올 지수 목록
INDEX_MAP: dict[str, tuple[str, ...]] = {
    "us": ("S&P 500", "NASDAQ 100", "DOW JONES", "S&P 100"),
    "jp": ("NIKKEI 225",),
    "eu": (
        "DAX", "MDAX", "TecDAX",
        "CAC_40", "CAC Mid 60",
        "AEX", "BEL 20", "IBEX 35",
        "FTSE 100", "Switzerland 20",
        "OMX Helsinki 25", "OMX Stockholm 30",
        "EURO STOXX 50",
    ),
    # kr, cn 은 pytickersymbols 에 없다 — 수기 목록 유지
}


def collect(region: str) -> dict[str, str]:
    """{티커: 회사명}. 지역이 맞는 티커만 남긴다."""
    from pytickersymbols import PyTickerSymbols

    src = PyTickerSymbols()
    found: dict[str, str] = {}
    for index in INDEX_MAP[region]:
        for stock in src.get_stocks_by_index(index):
            # 최상위 'symbol' 이 본국 거래소 티커다.
            # 'symbols' 리스트에는 프랑크푸르트 이중상장(.F)·미국 OTC 가 섞여 있어 쓰지 않는다.
            ticker = (stock.get("symbol") or "").strip()
            if not ticker:
                continue
            if region == "us" and "." in ticker:
                continue  # 접미사 없는 미국 티커만
            if region_of(ticker) != region:
                continue
            found.setdefault(ticker, (stock.get("name") or "").strip())
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="지수 구성종목을 시드에 병합")
    ap.add_argument("--regions", default="us,jp,eu")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for region in [r.strip() for r in args.regions.split(",") if r.strip()]:
        if region not in INDEX_MAP:
            print(f"[{region}] pytickersymbols 미지원 — 수기 목록 유지", file=sys.stderr)
            continue

        existing = load_seeds(region)
        existing_upper = {t.upper() for t in existing}
        incoming = collect(region)
        new = {t: n for t, n in incoming.items() if t.upper() not in existing_upper}

        print(f"[{region}] 기존 {len(existing)}종목 + 지수에서 신규 {len(new)}종목 "
              f"= {len(existing) + len(new)}종목")
        if args.dry_run:
            for t, n in sorted(new.items()):
                print(f"    + {t:<12} {n}")
            continue
        if not new:
            continue

        path = SEEDS / f"{region}.txt"
        block = [
            "",
            f"# ---- 이하 {', '.join(INDEX_MAP[region])} 구성종목에서 자동 병합 ----",
            "# 출처: pytickersymbols (오프라인 번들 데이터). scripts/merge_index_seeds.py 로 재생성.",
        ]
        block += [f"{t:<12}# {n}" if n else t for t, n in sorted(new.items())]
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(block) + "\n")
        print(f"    → {path} 에 추가")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
