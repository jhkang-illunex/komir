# -*- coding: utf-8 -*-
"""엔트리 디스패처: python -m geo_collectors <collect-news|collect-gdelt> [opts]

2026-08-06 DMZ/in-house 물리 분리로 inhouse/geo/__main__.py의 collect-news/collect-gdelt
서브커맨드를 여기로 옮김(로직 변경 없음 — DMZ 존은 원본 다운로드/수집 후 파일로 전달만
하고 LLM·지수 산출 등 in-house 로직은 갖지 않는다). gkg-parse 이하 단계는 여전히
inhouse/geo의 `python -m geo`가 담당."""
import argparse, sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="geo_collectors", description="DMZ 비정형 뉴스 수집기")
    sub = ap.add_subparsers(dest="stage", required=True)
    pcn = sub.add_parser("collect-news", help="[0] Google News RSS 수집 → inbox 투척(komis 이식)")
    pcn.add_argument("--minerals", default=None, help="쉼표구분 CU,NI,CO,LI,REE(기본 전체)")
    pcn.add_argument("--days", type=int, default=90)
    pcg = sub.add_parser("collect-gdelt", help="[0] GDELT DOC API 수집 → inbox 투척(komis 이식)")
    pcg.add_argument("--minerals", default=None, help="쉼표구분 CU,NI,CO,LI,REE(기본 전체)")
    pcg.add_argument("--days", type=int, default=90)
    args = ap.parse_args(argv)

    if args.stage == "collect-news":
        from . import gnews
        gnews.run(args.minerals.split(",") if args.minerals else None, args.days)
    elif args.stage == "collect-gdelt":
        from . import gdelt
        gdelt.run(args.minerals.split(",") if args.minerals else None, args.days)
    else:
        ap.print_help(); sys.exit(1)


if __name__ == "__main__":
    main()
