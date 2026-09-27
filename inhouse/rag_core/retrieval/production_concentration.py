"""세계 총계 대비 생산 1위국 비중 adapter."""
from __future__ import annotations
from common.komis_raw import KomisRawDataRepository, RawDataAccessError
from .evidence import Evidence

def fetch_production_concentration_evidence(mineral: str, *, year: int | None = None,
                                            repo: KomisRawDataRepository | None = None):
    try:
        dataset = (repo or KomisRawDataRepository()).fetch_top_producer_mineral_shares(
            year=year, top_n=1, mineral_names=[mineral])
    except RawDataAccessError as exc:
        return [], [f"production_concentration_query_failed:{type(exc).__name__}"]
    if not dataset.rows:
        return [], ["production_concentration_not_found"]
    row = dataset.rows[0]
    text = ("| 광종 | 기준연도 | 생산 1위국 | 생산 1위국 비중 |\n|---|---|---|---|\n"
            f"| {row.get('mineral','')} | {row.get('year','')} | {row.get('country','')} | {row.get('share_pct','')}% |")
    return [Evidence(kind="structured", source="public.KO_RSRC_PRDCTN_QUTY", section="생산 집중도", text=text)], []
