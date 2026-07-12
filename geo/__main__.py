# -*- coding: utf-8 -*-
"""엔트리 디스패처: python -m geo <ingest|extract|index> [opts]
Docker ENTRYPOINT 도 이걸 사용."""
import argparse, sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="geo", description="지정학 위기 지수 파이프라인")
    sub = ap.add_subparsers(dest="stage", required=True)
    pcn = sub.add_parser("collect-news", help="[0] Google News RSS 수집 → inbox 투척(komis 이식)")
    pcn.add_argument("--minerals", default=None, help="쉼표구분 CU,NI,CO,LI,REE(기본 전체)")
    pcn.add_argument("--days", type=int, default=90)
    pcg = sub.add_parser("collect-gdelt", help="[0] GDELT DOC API 수집 → inbox 투척(komis 이식)")
    pcg.add_argument("--minerals", default=None, help="쉼표구분 CU,NI,CO,LI,REE(기본 전체)")
    pcg.add_argument("--days", type=int, default=90)
    pgp = sub.add_parser("gkg-parse", help="[0] GKG 벌크(gkg_bulk_download.py 산출) → geo_event 파싱·적재")
    pgp.add_argument("--bulk-root", required=True, help="gkg_bulk_download.py --dest와 동일 경로")
    pgp.add_argument("--year-from", type=int, default=2016)
    pgp.add_argument("--year-to", type=int, default=None)
    pgp.add_argument("--worker", type=int, default=0)
    pgp.add_argument("--workers", type=int, default=1)
    pgv = sub.add_parser("gkg-verify", help="[0] GKG 규칙기반 후보를 실제 LLM으로 재검증")
    pgv.add_argument("--bulk-root", required=True)
    pgv.add_argument("--provider", default=None, help="openai_compat|anthropic (rule/mock 불가)")
    pgv.add_argument("--limit", type=int, default=500)
    pgv.add_argument("--min-severity", type=float, default=0.0)
    pgv.add_argument("--event-types", default=None, help="쉼표구분, 예: 정책,분쟁,제재")
    pib = sub.add_parser("ingest-bundles", help="[0.5] 수집기 일자별 번들 발견→inbox 전개→(기본) ingest 연쇄")
    pib.add_argument("--dir", default=None, help="번들 디렉토리(기본 $GEO_BUNDLE_DIR > $GEO_DATA/bundles_in)")
    pib.add_argument("--no-ingest", action="store_true")
    sub.add_parser("ingest", help="[1] inbox→archive 정리")
    pe = sub.add_parser("extract", help="[2] 이벤트 추출")
    pe.add_argument("--provider", default=None, help="rule|mock|openai_compat|anthropic")
    pi = sub.add_parser("index", help="[3] 지수 산출")
    pi.add_argument("--backtest", action="store_true")
    sub.add_parser("prob", help="[3-부속] 지수 확률화 — NB2 강도모델(다음주 심각이벤트 발생확률)")
    pr = sub.add_parser("refdata", help="USGS 공급집중 HHI 수집(오픈망)")
    pr.add_argument("--from", dest="y_from", type=int, default=2016)
    pr.add_argument("--to", dest="y_to", type=int, default=2026)
    pp = sub.add_parser("publish", help="지정학 지수(최종)만 공유/운영 DB에 적재")
    pp.add_argument("--db", default=None)
    px = sub.add_parser("okf-export", help="[비파괴] 정본 → OKF(마크다운+프론트매터) 번들 방출")
    px.add_argument("--root", default=None, help="출력 루트(기본 $GEO_DATA/okf)")
    pall = sub.add_parser("all", help="ingest→extract→index→OKF 연속 실행 (+선택 publish)")
    pall.add_argument("--provider", default=None)
    pall.add_argument("--publish-db", default=None)
    pall.add_argument("--no-okf", action="store_true", help="OKF 번들 생성 생략")
    args = ap.parse_args(argv)

    if args.stage == "collect-news":
        from .collectors import gnews
        gnews.run(args.minerals.split(",") if args.minerals else None, args.days)
    elif args.stage == "collect-gdelt":
        from .collectors import gdelt
        gdelt.run(args.minerals.split(",") if args.minerals else None, args.days)
    elif args.stage == "gkg-parse":
        from . import gkg_parse
        print(gkg_parse.run(args.bulk_root, args.year_from, args.year_to, args.worker, args.workers))
    elif args.stage == "gkg-verify":
        from . import gkg_verify
        et = tuple(args.event_types.split(",")) if args.event_types else ()
        print(gkg_verify.run(args.bulk_root, args.provider, args.limit, args.min_severity, et))
    elif args.stage == "ingest-bundles":
        from . import ingest_bundles; ingest_bundles.run(args.dir, not args.no_ingest)
    elif args.stage == "ingest":
        from . import ingest; ingest.run()
    elif args.stage == "extract":
        from . import extract; extract.run(provider_override=args.provider)
    elif args.stage == "index":
        from . import index; index.run(backtest=args.backtest)
    elif args.stage == "prob":
        from . import prob_model; prob_model.run()
    elif args.stage == "refdata":
        from . import refdata; refdata.run(args.y_from, args.y_to)
    elif args.stage == "publish":
        from . import publish; publish.run(args.db)
    elif args.stage == "okf-export":
        from . import okf
        okf.export(None if not args.root else __import__("pathlib").Path(args.root))
    elif args.stage == "all":
        from . import ingest, extract, index, publish, okf
        ingest.run(); extract.run(provider_override=args.provider); index.run()
        if not args.no_okf:
            okf.export()                       # 지수 산출 직후 OKF 번들 자동 생성
        if args.publish_db:
            publish.run(args.publish_db)
    else:
        ap.print_help(); sys.exit(1)


if __name__ == "__main__":
    main()
