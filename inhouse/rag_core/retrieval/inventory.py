"""KOMIS 광물 재고량의 읽기 전용 어댑터."""
from __future__ import annotations

from datetime import date

from common.db import pg_connect
from .evidence import Evidence


def fetch_inventory_evidence(mineral: str | None, *, basis: str | None = None,
                             price_criterion_serial: int | None = None) -> tuple[list[Evidence], list[str]]:
    """`ko_mnrl_prc.invt`만 재고로 반환하고 가격 값과 섞지 않는다.

    광종은 매핑 테이블에서 가격기준 일련번호로 해소하고, 그 일련번호를
    `ko_mnrl_prc_crtr`에 연결해 재고 기준명(`prc_crtr`)을 함께 보존한다.
    """
    con = None
    try:
        con = pg_connect()
        with con.cursor() as cur:
            criterion_filter = ""
            params: list[object] = [mineral] if mineral else []
            mineral_filter = "m.mnrl_nm_ko = %s" if mineral else "pm.mnrl_prc_crtr_sn = %s"
            if not mineral:
                params = [price_criterion_serial]
            if basis:
                criterion_filter = " AND c.prc_crtr ILIKE %s"
            params.append(date.today().strftime("%Y%m%d"))
            if basis:
                # SQL의 기준명 조건은 기준일 조건 뒤에 위치한다.
                params.append(f"%{basis}%")
            params.append(1)
            cur.execute(
                "SELECT p.crtr_ymd, p.invt, c.prc_crtr, c.weig_unit_cd, m.mnrl_nm_ko "
                "FROM public.ai_prc_mnrl_map pm "
                "JOIN public.ai_mnrl_mst m ON m.mnrknd_unq_cd = pm.mnrknd_unq_cd "
                "JOIN public.ko_mnrl_prc_crtr c ON c.mnrl_prc_crtr_sn = pm.mnrl_prc_crtr_sn "
                "JOIN public.ko_mnrl_prc p ON p.mnrl_prc_crtr_sn = c.mnrl_prc_crtr_sn "
                "WHERE " + mineral_filter + " AND pm.use_yn = 'Y' "
                "AND p.status = 'Y' AND p.last_del_dt IS NULL "
                "AND p.invt IS NOT NULL AND p.invt <> 0 AND p.crtr_ymd <= %s" + criterion_filter +
                " ORDER BY p.crtr_ymd DESC, p.mnrl_prc_crtr_sn ASC LIMIT %s",
                tuple(params),
            )
            row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        return [], [f"inventory_query_failed:{type(exc).__name__}"]
    finally:
        if con is not None:
            con.close()
    if not row:
        return [], ["inventory_not_found"]
    day, value, criterion, weight_unit, mineral_name = row
    # weig_unit_cd는 기준정보의 원시 단위 코드다. 별도 단위 사전 확인 전에는
    # 임의로 ton/kg을 붙이지 않고 코드 그대로 보존한다.
    text = "\n".join((
        "| 기준일 | 광종 | 재고 종류 | 재고량 | 원시 단위 코드 |",
        "|---|---|---|---:|---|",
        f"| {day} | {mineral_name} | {criterion or '기준 미확인'} | {value} | {weight_unit or '미확인'} |",
    ))
    return [Evidence(kind="structured", source="public.ko_mnrl_prc + public.ko_mnrl_prc_crtr",
                     section=f"KOMIS 재고량 · {mineral_name}", text=text, as_of=str(day),
                     unit=f"재고기준={criterion or '미확인'}")], []
