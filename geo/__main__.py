# -*- coding: utf-8 -*-
"""엔트리 디스패처: python -m geo <ingest|extract|index> [opts]
Docker ENTRYPOINT 도 이걸 사용."""
import argparse, sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="geo", description="지정학 위기 지수 파이프라인")
    sub = ap.add_subparsers(dest="stage", required=True)
    sub.add_parser("ingest", help="[1] inbox→archive 정리")
    pe = sub.add_parser("extract", help="[2] 이벤트 추출")
    pe.add_argument("--provider", default=None, help="rule|mock|openai_compat|anthropic")
    pi = sub.add_parser("index", help="[3] 지수 산출")
    pi.add_argument("--backtest", action="store_true")
    pr = sub.add_parser("refdata", help="USGS 공급집중 HHI 수집(오픈망)")
    pr.add_argument("--from", dest="y_from", type=int, default=2016)
    pr.add_argument("--to", dest="y_to", type=int, default=2026)
    pp = sub.add_parser("publish", help="지정학 지수(최종)만 공유/운영 DB에 적재")
    pp.add_argument("--db", default=None)
    pall = sub.add_parser("all", help="ingest→extract→index 연속 실행 (+선택 publish)")
    pall.add_argument("--provider", default=None)
    pall.add_argument("--publish-db", default=None)
    args = ap.parse_args(argv)

    if args.stage == "ingest":
        from . import ingest; ingest.run()
    elif args.stage == "extract":
        from . import extract; extract.run(provider_override=args.provider)
    elif args.stage == "index":
        from . import index; index.run(backtest=args.backtest)
    elif args.stage == "refdata":
        from . import refdata; refdata.run(args.y_from, args.y_to)
    elif args.stage == "publish":
        from . import publish; publish.run(args.db)
    elif args.stage == "all":
        from . import ingest, extract, index, publish
        ingest.run(); extract.run(provider_override=args.provider); index.run()
        if args.publish_db:
            publish.run(args.publish_db)
    else:
        ap.print_help(); sys.exit(1)


if __name__ == "__main__":
    main()
