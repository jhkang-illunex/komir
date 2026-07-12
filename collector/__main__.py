# -*- coding: utf-8 -*-
"""komir 수집기 — 분석기(geo)와 분리된 독립 도커/서버에서 실행.

  python -m collector run [--only gnews,gdelt,gkg,us_trade,cn_trade] [--days 90]
  python -m collector daemon [--interval-mins 60]   # 도커 기본 CMD

수집기는 $COLLECT_OUT(공유 NAS 권장)에만 쓴다 — 분석기와 코드 의존 없음(파일 계약만).
"""
import argparse, logging, time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

ALL = ["gkg", "gnews", "gdelt", "us_trade", "cn_trade"]


def run_once(only=None, days: int = 7):
    only = only or ALL
    results = {}
    if "gkg" in only:
        from . import gkg_incremental
        results["gkg"] = gkg_incremental.run()
    if "gnews" in only:
        from . import gnews
        results["gnews"] = gnews.run(None, days)
    if "gdelt" in only:
        from . import gdelt_doc
        results["gdelt"] = gdelt_doc.run(None, days)
    if "us_trade" in only:
        from . import us_trade
        results["us_trade"] = us_trade.run()
    if "cn_trade" in only:
        from . import cn_trade
        results["cn_trade"] = cn_trade.run()
    print(f"[collector] 완료: {results}")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(prog="collector")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run", help="전체(또는 --only) 1회 수집")
    pr.add_argument("--only", default=None, help=f"쉼표구분 {','.join(ALL)}")
    pr.add_argument("--days", type=int, default=7, help="뉴스 수집 소급 일수(기본 7)")
    pd_ = sub.add_parser("daemon", help="주기 실행(도커 기본)")
    pd_.add_argument("--interval-mins", type=int, default=60)
    pd_.add_argument("--only", default=None)
    pd_.add_argument("--days", type=int, default=7)
    a = ap.parse_args(argv)

    only = a.only.split(",") if a.only else None
    if a.cmd == "run":
        run_once(only, a.days)
    else:
        while True:
            try:
                run_once(only, a.days)
            except Exception as e:          # 개별 주기 실패가 데몬을 죽이지 않게
                logging.getLogger("collector").exception("주기 실행 실패: %s", e)
            time.sleep(a.interval_mins * 60)


if __name__ == "__main__":
    main()
