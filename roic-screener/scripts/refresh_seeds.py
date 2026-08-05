#!/usr/bin/env python3
"""시드 리스트를 공개 소스에서 갱신한다. **로컬에서** 실행할 것.

이 스크립트는 네트워크가 막힌 환경에서 작성되어 실행 검증되지 않았다.
깨지면 에러를 그대로 보고해 주면 고칠 수 있다.

    python scripts/refresh_seeds.py --region us     # Wikipedia S&P 500
    python scripts/refresh_seeds.py --region cn     # akshare A주 전종목 시총 상위
    python scripts/refresh_seeds.py --region us --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEEDS = ROOT / "seeds"
sys.path.insert(0, str(ROOT))

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def fetch_us() -> list[tuple[str, str]]:
    """Wikipedia S&P 500 표. yfinance 는 'BRK.B' 대신 'BRK-B' 를 쓴다."""
    import pandas as pd

    tables = pd.read_html(SP500_URL)
    df = next(t for t in tables if "Symbol" in t.columns)
    out = []
    for _, row in df.iterrows():
        sym = str(row["Symbol"]).strip().replace(".", "-")
        name = str(row.get("Security", "")).strip()
        out.append((sym, name))
    return out


def fetch_cn(limit: int = 300) -> list[tuple[str, str]]:
    """akshare A주 전종목 시총 스냅샷 — 중국만 진짜 시총 순위를 무료로 쓸 수 있다."""
    import akshare as ak

    df = ak.stock_zh_a_spot_em()
    col_cap = next(c for c in df.columns if "总市值" in str(c))
    col_code = next(c for c in df.columns if "代码" in str(c))
    col_name = next((c for c in df.columns if "名称" in str(c)), None)

    df = df.dropna(subset=[col_cap]).sort_values(col_cap, ascending=False).head(limit)
    out = []
    for _, row in df.iterrows():
        code = str(row[col_code]).zfill(6)
        name = str(row[col_name]) if col_name else ""
        if code.startswith(("60", "68")):
            out.append((f"{code}.SS", name))
        elif code.startswith(("00", "30")):
            out.append((f"{code}.SZ", name))
    return out


HEADERS = {
    "us": "# 미국 시드 — Wikipedia S&P 500 자동 생성\n"
          "# 주의: S&P 500 은 미국 대형주 지수라 시총 상위 100은 거의 다 포함되지만,\n"
          "#       비지수 편입 대형주(예: 최근 상장)는 빠질 수 있다.\n",
    "cn": "# 중국 시드 — akshare A주 전종목 시총 상위 자동 생성 (홍콩 미포함)\n"
          "# 홍콩 종목이 필요하면 기존 cn.txt 의 .HK 블록을 다시 붙일 것.\n",
}

FETCHERS = {"us": fetch_us, "cn": fetch_cn}


def main() -> int:
    p = argparse.ArgumentParser(description="시드 리스트 갱신")
    p.add_argument("--region", required=True, choices=sorted(FETCHERS))
    p.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 결과만 출력")
    p.add_argument("--limit", type=int, default=300, help="중국: 상위 N종목")
    args = p.parse_args()

    fetch = FETCHERS[args.region]
    rows = fetch(args.limit) if args.region == "cn" else fetch()
    if not rows:
        print("수집 결과가 비어 있습니다.", file=sys.stderr)
        return 1

    body = "\n".join(f"{tk:<12}# {name}" if name else tk for tk, name in rows)
    content = HEADERS.get(args.region, "") + body + "\n"

    if args.dry_run:
        print(content)
        print(f"\n-- {len(rows)}종목 (dry-run, 저장하지 않음)", file=sys.stderr)
        return 0

    target = SEEDS / f"{args.region}.txt"
    backup = SEEDS / f"{args.region}.txt.bak"
    if target.exists():
        backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"기존 파일 백업: {backup}")
    target.write_text(content, encoding="utf-8")
    print(f"{target} 갱신 완료 — {len(rows)}종목")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
