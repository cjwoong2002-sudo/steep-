#!/usr/bin/env python3
"""엑셀 레이아웃 샘플을 만든다. **숫자는 전부 가상이다.**

5개 지역 전체 수집은 1시간 이상 걸린다. 그 전에 출력 형식이 원하는 모양인지
확인할 수 있게 하려는 용도다. 티커는 SAMPLE-* 로 두어 실제 종목과 혼동될 수 없게 했다.

    python scripts/make_layout_sample.py 레이아웃_샘플.xlsx
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from conftest import FakeProvider, make_company  # noqa: E402

from roic_screener.config import RoicParams, ScreenParams  # noqa: E402
from roic_screener.excel import write_report  # noqa: E402
from roic_screener.screener import run_screen  # noqa: E402

# (티커, 표시명, 통화, 시총, EBIT 배수, 섹터, 업종)
SAMPLES = [
    ("SAMPLE-A", "샘플기업 A ※가상데이터", "USD", 400e9, 3.4, "Technology", "Semiconductors"),
    ("SAMPLE-B", "샘플기업 B ※가상데이터", "USD", 320e9, 2.8, "Consumer Cyclical", "Luxury Goods"),
    ("SAMPLE-C", "샘플기업 C ※가상데이터", "USD", 260e9, 2.2, "Healthcare", "Drug Manufacturers"),
    ("SAMPLE-D", "샘플기업 D ※가상데이터", "USD", 180e9, 1.6, "Industrials", "Machinery"),
    ("SAMPLE-E", "샘플기업 E ※가상데이터", "USD", 150e9, 1.1, "Technology", "Software"),
    ("SAMPLE-F.KS", "샘플기업 F ※가상데이터", "KRW", 300e12, 2.5, "Technology", "Semiconductors"),
    ("SAMPLE-G.KS", "샘플기업 G ※가상데이터", "KRW", 120e12, 1.8, "Consumer Cyclical", "Auto Manufacturers"),
    ("SAMPLE-H.KS", "샘플은행 H ※가상데이터", "KRW", 90e12, 4.0, "Financial Services", "Banks - Regional"),
]


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "레이아웃_샘플.xlsx")

    companies = {
        tk: make_company(
            tk, name=name, currency=cur, market_cap=cap,
            ebit_scale=scale, sector=sector, industry=industry,
        )
        for tk, name, cur, cap, scale, sector, industry in SAMPLES
    }
    seeds = out.parent / "_sample_seeds"
    seeds.mkdir(parents=True, exist_ok=True)
    (seeds / "us.txt").write_text(
        "\n".join(t for t in companies if "." not in t) + "\nBADTICKER\n", encoding="utf-8"
    )
    (seeds / "kr.txt").write_text(
        "\n".join(t for t in companies if t.endswith(".KS")) + "\n", encoding="utf-8"
    )

    params = ScreenParams(
        top_n_marketcap=100,
        top_n_roic=30,
        window_start=dt.date(2024, 1, 1),
        window_end=dt.date(2026, 6, 30),
        roic=RoicParams(min_invested_capital_usd=1.0),
    )
    result = run_screen(
        FakeProvider(companies, fx={"USDKRW=X": 1350.0}),
        ["us", "kr"],
        params,
        seed_dir=seeds,
    )
    result.notes.insert(
        0,
        "★ 이 파일은 레이아웃 확인용 샘플입니다. 모든 숫자는 가상이며 실제 시장 데이터가 "
        "아닙니다. 실제 결과는 `python run.py --regions all` 로 생성하세요.",
    )
    write_report(result, out)

    for p in seeds.glob("*.txt"):
        p.unlink()
    seeds.rmdir()

    print(f"레이아웃 샘플 생성: {out.resolve()}")
    print("※ 숫자는 전부 가상입니다. 형식 확인 용도로만 쓰세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
