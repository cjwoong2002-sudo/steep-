"""명령줄 인터페이스.

    python run.py --regions us
    python run.py --regions kr,us,jp,cn,eu --out 결과.xlsx
    python run.py --regions cn --akshare        # 중국은 전종목 시총 순위 사용
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

from .config import ALL_REGIONS, RoicParams, ScreenParams, WINDOW_END, WINDOW_START
from .excel import default_filename, write_report
from .provider import YFinanceProvider
from .screener import run_screen
from .universe import load_seeds


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="roic-screener",
        description="무료 소스(Yahoo/akshare)로 지역별 ROIC 상위 기업을 뽑아 엑셀로 출력",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--regions",
        default="us",
        help=f"쉼표 구분. 가능: {','.join(ALL_REGIONS)} 또는 all",
    )
    p.add_argument("--out", default=None, help="출력 xlsx 경로 (기본: 자동 생성)")
    p.add_argument("--top-mcap", type=int, default=100, help="지역별 시총 상위 N을 유니버스로")
    p.add_argument("--top-roic", type=int, default=30, help="최종 선정 종목 수")
    p.add_argument("--window-start", type=_date, default=WINDOW_START)
    p.add_argument("--window-end", type=_date, default=WINDOW_END)
    p.add_argument(
        "--exclude-goodwill",
        action="store_true",
        help="투하자본에서 영업권 차감 (인수로 만든 자본을 제외한 ROIC)",
    )
    p.add_argument(
        "--min-ic-usd",
        type=float,
        default=50e6,
        help="평균 투하자본 하한(USD). 껍데기 법인의 ROIC 폭발을 막는다",
    )
    p.add_argument(
        "--min-coverage",
        type=float,
        default=0.55,
        help="측정창 커버리지 하한(0~1). 미달 종목은 제외종목 시트로 보낸다",
    )
    p.add_argument("--cache-dir", default=".cache", help="수집 결과 디스크 캐시 위치")
    p.add_argument("--cache-days", type=float, default=1.0, help="캐시 유효기간(일)")
    p.add_argument(
        "--interval",
        type=float,
        default=1.2,
        help="Yahoo 호출 간 최소 대기(초). 낮추면 IP 차단 위험이 커진다",
    )
    p.add_argument("--retries", type=int, default=3, help="호출 실패 시 재시도 횟수")
    p.add_argument("--seed-dir", default=None, help="시드 파일 디렉터리 (기본: seeds/)")
    p.add_argument(
        "--akshare",
        action="store_true",
        help="중국은 akshare 로 전종목 시총 순위를 받아 진짜 상위 100을 쓴다",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    regions = ALL_REGIONS if args.regions.strip() == "all" else [
        r.strip().lower() for r in args.regions.split(",") if r.strip()
    ]
    unknown = [r for r in regions if r not in ALL_REGIONS]
    if unknown:
        print(f"알 수 없는 지역: {unknown}. 가능: {ALL_REGIONS}", file=sys.stderr)
        return 2

    params = ScreenParams(
        top_n_marketcap=args.top_mcap,
        top_n_roic=args.top_roic,
        window_start=args.window_start,
        window_end=args.window_end,
        roic=RoicParams(
            exclude_goodwill=args.exclude_goodwill,
            min_invested_capital_usd=args.min_ic_usd,
            min_coverage_ratio=args.min_coverage,
        ),
    )

    provider = YFinanceProvider(
        Path(args.cache_dir),
        cache_ttl_days=args.cache_days,
        min_interval=args.interval,
        max_retries=args.retries,
    )

    # 실제 시드 개수로 호출량과 소요시간을 추정한다. 1시간 넘게 걸릴 수 있어
    # 시작 전에 규모를 보여주는 게 낫다.
    seed_dir = Path(args.seed_dir) if args.seed_dir else None
    try:
        n_seeds = sum(len(load_seeds(r, seed_dir)) for r in regions)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2
    n_full = sum(min(args.top_mcap, len(load_seeds(r, seed_dir))) for r in regions)
    est_calls = n_seeds + int(n_full * 0.75) * 6  # 2패스는 업종 제외 후 약 3/4만 진행
    est_min = est_calls * (args.interval + 0.2) / 60
    print(
        f"지역 {regions} / 후보 {n_seeds:,}종목 / 예상 API 호출 약 {est_calls:,}회 "
        f"→ 캐시가 비어 있으면 약 {est_min:.0f}분 (캐시가 있으면 즉시)"
    )

    result = run_screen(
        provider,
        regions,
        params,
        seed_dir=Path(args.seed_dir) if args.seed_dir else None,
        use_akshare_for_cn=args.akshare,
        on_progress=lambda m: print(m, flush=True),
    )

    out = Path(args.out) if args.out else Path(default_filename(regions))
    write_report(result, out)

    print()
    print(f"엑셀 저장: {out.resolve()}")
    for region in regions:
        n_top = len(result.top.get(region, []))
        n_uni = len(result.universe.get(region, []))
        print(f"  {region}: 유니버스 {n_uni}종목 → 선정 {n_top}종목")
    print(f"  제외 {len(result.excluded)}건 / 조회실패 {len(result.errors)}건")
    if result.errors:
        print("  ※ '조회실패' 시트에서 티커 오류를 확인하고 seeds/*.txt 를 고치세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
