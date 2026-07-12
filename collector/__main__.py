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
    pd_ = sub.add_parser("daemon", help="주기 실행(도커 기본) — 날짜 전환 시 자동 번들링")
    pd_.add_argument("--interval-mins", type=int, default=60)
    pd_.add_argument("--only", default=None)
    pd_.add_argument("--days", type=int, default=7)
    pd_.add_argument("--no-bundle", action="store_true", help="일자별 번들링 비활성(루즈 파일 유지)")
    pd_.add_argument("--bundle-each", action="store_true",
                     help="매 주기 직후 번들(예: --interval-mins 1440과 조합해 일일 운영)")
    sub.add_parser("bundle", help="현재 inbox·gkg 루즈 파일을 collect_YYYYMMDD.zip으로 번들(cron용)")
    pdy = sub.add_parser("daily", help="일일 운영 정본: 전체 1회 수집(GKG는 그날치 캐치업) + 즉시 zip 번들")
    pdy.add_argument("--only", default=None)
    pdy.add_argument("--days", type=int, default=2, help="뉴스 소급 일수(기본 2 — 경계 유실 방지)")
    a = ap.parse_args(argv)

    if a.cmd == "bundle":
        from . import bundler
        bundler.run()
        return
    if a.cmd == "daily":
        from . import bundler
        only = a.only.split(",") if a.only else None
        run_once(only, a.days)
        bundler.run()
        return
    only = a.only.split(",") if a.only else None
    if a.cmd == "run":
        run_once(only, a.days)
    else:
        from datetime import date
        cur_day = date.today()
        while True:
            try:
                run_once(only, a.days)
            except Exception as e:          # 개별 주기 실패가 데몬을 죽이지 않게
                logging.getLogger("collector").exception("주기 실행 실패: %s", e)
            if getattr(a, "bundle_each", False):
                try:
                    from . import bundler
                    bundler.run()
                except Exception as e:
                    logging.getLogger("collector").exception("번들링 실패: %s", e)
            # 날짜 전환 감지 → 어제까지 쌓인 루즈 파일을 번들로 인도
            elif not getattr(a, "no_bundle", False) and date.today() != cur_day:
                try:
                    from . import bundler
                    bundler.run(cur_day.strftime("%Y%m%d"))
                except Exception as e:
                    logging.getLogger("collector").exception("번들링 실패: %s", e)
                cur_day = date.today()
            time.sleep(a.interval_mins * 60)


if __name__ == "__main__":
    main()
