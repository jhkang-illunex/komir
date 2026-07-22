# -*- coding: utf-8 -*-
"""GKG 2.1 원본(collectors/gkg_bulk_download.py로 받은 zip) → GeoEvent 파싱·적재.

GKG는 기사 본문이 없고 구조화 필드만 준다(27개 탭 구분 컬럼). 그래서 llm/rule.py처럼
본문 정규식 매칭이 아니라 **테마코드·톤·위치** 구조화 필드를 규칙 매핑한다.

광종 판별
    CU/NI  — V2Themes의 전용 World Bank 코드(WB_2934_COPPER/WB_2935_NICKEL)로 정확 매칭
             (실측 확인: 2016·2022 샘플 둘 다 존재, 코발트/리튬/희토류는 전용 코드 없음)
    CO/LI/REE — 전용 코드가 없어 DocumentIdentifier(URL)·AllNames·Organizations·Persons를
             합쳐 키워드 매칭(cobalt/lithium/rare earth 등) — CU/NI보다 신뢰도 낮게 처리.

severity/event_type
    1순위: V2Themes에 제재·분쟁·정책규제 관련 코드가 있으면 llm/rule.py와 동일한
           event_type·심각도 체계(수출규제=3·제재=3·분쟁=2·정책=1 등)로 매핑
           (오프셋 근접성 검증됨 — 상품 테마와 같은 문단인지 확인, THEME_PROXIMITY_CHARS).
    2순위(매칭 없으면="뉴스" 폴백): V2Tone 평균톤만으로 심각도 추정.
        ⚠️ 실측(2026-07-06) 결과 이 폴백 티어는 "채굴 관련 테마 동반출현" 요구를 추가해도 정밀도가
        안 오른다 — GDELT 자체가 "copper"를 맥주 브루잉 설비·동전 등과 혼동해 채굴테마까지 잘못
        동반 태깅하는 사례를 확인함(예: IPA 맥주 기사에 WB_895_MINING_SYSTEMS가 실제로 붙어있었음).
        본문이 없는 GKG 구조상 규칙만으로는 한계가 명확 → indexer.py가 이 티어를 지수 계산에서
        기본 제외하고, gkg_verify.py(LLM 재검증)를 거쳐야 승격되도록 설계했다.

산출은 기존 geo/store.py의 geo_events.parquet에 그대로 append —
index.py는 extractor="rule"/provider="gkg"인 것도 다른 geo_event와 동일하게 취급하되,
event_type="뉴스"(미검증 폴백)는 지수 계산에서 제외한다(gkg_verify.py로 승격 전까지).

CLI:
    python -m geo.gkg_parse --bulk-root /mnt/.../bulk/gdelt --year-from 2016 --year-to 2016
    python -m geo.gkg_parse --bulk-root ... --worker 0 --workers 4   # 병렬(연도 내 파일 분배)
"""
from __future__ import annotations
import argparse, hashlib, os, zipfile
from datetime import datetime

from . import store
from .gkg_relevance import is_relevant

# ── GKG 2.1 컬럼 인덱스(0-based, 탭 구분 27필드) ──────────────────────────────
C_ID, C_DATE, C_SRCID, C_SRCNAME, C_DOCID = 0, 1, 2, 3, 4
C_V1COUNTS, C_V2COUNTS = 5, 6
C_V1THEMES, C_V2THEMES = 7, 8
C_V1LOC, C_V2LOC = 9, 10
C_V1PERSON, C_V2PERSON = 11, 12
C_V1ORG, C_V2ORG = 13, 14
C_TONE = 15
C_DATES, C_GCAM = 16, 17
C_ALLNAMES = 23
N_FIELDS = 27

# ── 광종 판별 ────────────────────────────────────────────────────────────────
# 전용 테마코드(실측 확인됨: 2016-01·2022-06 샘플 둘 다 존재)
THEME_COMMODITY = {"WB_2934_COPPER": "CU", "WB_2935_NICKEL": "NI"}
# 전용 코드 없는 3종 — 키워드 매칭(신뢰도 낮음, confidence로 구분).
# REE는 사내 확정(2026-07-02, 메모리 기록됨)상 네오디뮴(Nd)이 대상원소라 Nd 관련어를 최우선으로 두고,
# "rare earth" 범용어는 최후순위 폴백으로만 둔다(범용어일수록 무관 기사 유입 위험 큼).
KEYWORD_COMMODITY = {
    "CO": ("cobalt",),
    "LI": ("lithium",),
    "REE": ("neodymium", "ndfeb", "nd magnet", "dysprosium", "rare earth"),
}
# 2026-07-20 /goal 재설계: 기존엔 아래 SECONDARY_SIGNAL_KEYWORDS 게이트가 CO/LI/REE(키워드매칭
# 광종)에만 걸리고 CU/NI(GDELT 전용 테마코드 매칭)는 관련성 검사를 아예 안 거치는 구조적 공백이
# 있었다 — 단순임의표본(n=200) 재추정 결과 오염률 71.4%(정정후)의 근본원인으로 확정(WORKLOG
# 2026-07-20). is_relevant()(geo/gkg_relevance.py, 상품별 이름·생산기업·노이즈어 인식,
# 캘리브레이션 94.3%/독립검증셋도 동급)로 대체하고 CU/NI 포함 전 상품·전 티어에 동일하게 적용한다.

# ── event_type/severity — llm/rule.py의 체계와 동일하게 맞춤(테마코드 기반) ───
# (테마 부분문자열, event_type, direction, target, severity)
THEME_RULES = [
    ("SANCTION", "제재", "supply_down", "supply", 3),
    ("EMBARGO", "제재", "supply_down", "supply", 3),
    ("ARMEDCONFLICT", "분쟁", "supply_down", "supply", 2),
    ("REBELLION", "분쟁", "supply_down", "supply", 2),
    ("WB_2433_CONFLICT_AND_VIOLENCE", "분쟁", "supply_down", "supply", 2),
    ("WB_554_MINING_POLICY_LAWS_AND_REGULATIONS", "정책", "supply_down", "supply", 1),
    ("EPU_POLICY", "정책", "supply_down", "supply", 1),
    ("NATURAL_DISASTER", "재해", "supply_down", "production", 2),
]
# 상품 테마코드와 사건유형 테마코드가 "같은 문단"(근접 오프셋)에 있는지 확인하는 최대 거리(글자 수).
# 실측(2026-07-06): 이 검증 없이는 CU/NI "분쟁" 표본의 절반 이상이 무관 기사(나이지리아 국회 폭탄테러,
# 미시간 수돗물 사태 등)였음 — 긴 기사에 상품명과 무관한 테마가 우연히 동반 태깅되는 경우가 흔함.
THEME_PROXIMITY_CHARS = 300

# 실측 오탐 사례(예: "구리 절도범 수배" 지역기사가 WB_2934_COPPER로 잡힘) 제거용.
# THEME_RULES에 이미 매칭된 건(제재/분쟁/정책/재해)은 그대로 두고, 그 외(폴백 "뉴스" 티어)에서만
# 아래 테마가 있으면 공급망·지정학과 무관한 지역 사건으로 보고 이벤트 생성을 스킵한다.
NOISE_THEMES = ("CRIME_COMMON_ROBBERY", "TAX_FNCACT_BURGLAR", "CRIME_COMMON_THEFT",
                "TAX_FNCACT_THIEF", "CRISISLEX_C07_SAFETY")


def _parse_theme_offsets(v2themes: str) -> dict[str, list[int]]:
    """V2Themes "CODE,offset;CODE,offset;..." → {code: [offset,...]}."""
    out: dict[str, list[int]] = {}
    if not v2themes:
        return out
    for item in v2themes.split(";"):
        if "," not in item:
            continue
        code, _, off = item.rpartition(",")
        try:
            out.setdefault(code, []).append(int(off))
        except ValueError:
            continue
    return out


def _min_distance(offs_a: list[int], offs_b: list[int]) -> int:
    if not offs_a or not offs_b:
        return 10**9
    return min(abs(a - b) for a in offs_a for b in offs_b)


def _parse_tone(field: str) -> float | None:
    """V2Tone 첫 값(평균 톤, 대략 -10~+10) — 파싱 실패시 None."""
    try:
        return float(field.split(",")[0])
    except (ValueError, IndexError):
        return None


def _tone_severity(tone: float | None) -> tuple[float, float]:
    """테마 규칙 미매칭시 폴백: 평균톤만으로 (severity, confidence) 추정."""
    if tone is None:
        return 0.0, 0.2
    if tone <= -5: return 3.0, 0.35
    if tone <= -2: return 2.0, 0.35
    if tone <= 0: return 1.0, 0.3
    return 0.0, 0.3


def _first_country(v2loc: str) -> str | None:
    """V2Locations 첫 항목의 지명(국가/지역 풀네임) — 코드가 아니라 사람이 읽는 이름."""
    if not v2loc:
        return None
    first = v2loc.split(";", 1)[0]
    parts = first.split("#")
    return parts[1] if len(parts) > 1 and parts[1] else None


def _theme_rule_for_commodity(theme_offsets: dict[str, list[int]], commodity_offs: list[int]):
    """THEME_RULES 중 상품 테마와 '같은 문단'(오프셋 근접)에 있는 것만 채택.
    commodity_offs가 없으면(키워드 매칭 광종) 근접성 검증 없이 전역 매칭(기존 방식)으로 폴백."""
    for pat, et, d, t, s in THEME_RULES:
        hit_offs = [o for code, offs in theme_offsets.items() if pat in code for o in offs]
        if not hit_offs:
            continue
        if not commodity_offs or _min_distance(commodity_offs, hit_offs) <= THEME_PROXIMITY_CHARS:
            return (et, d, t, s)
    return None


def parse_gkg_row(line: str) -> list[dict]:
    """GKG 한 행 → 0개 이상의 GeoEvent dict(광종별 1건). 광종 미매칭이면 빈 리스트."""
    f = line.rstrip("\n").split("\t")
    if len(f) < N_FIELDS:
        return []

    v2themes = f[C_V2THEMES]
    theme_offsets = _parse_theme_offsets(v2themes)
    doc_id = f[C_ID] or hashlib.md5(line.encode("utf-8", "ignore")).hexdigest()[:16]

    # 검색용 텍스트(키워드매칭 3종 전용 — GKG는 본문이 없어 URL·개체명으로 근사)
    kw_haystack = " ".join([f[C_DOCID], f[C_ALLNAMES], f[C_V2ORG], f[C_V2PERSON]]).lower()

    # 광종별 (매칭여부, 테마오프셋) — 오프셋은 THEME_COMMODITY(CU/NI)만 존재, 키워드매칭(CO/LI/REE)은 없음
    commodity_offs: dict[str, list[int]] = {}
    for code, cc in THEME_COMMODITY.items():
        if code in theme_offsets:
            commodity_offs.setdefault(cc, []).extend(theme_offsets[code])
    for cc, kws in KEYWORD_COMMODITY.items():
        if any(kw in kw_haystack for kw in kws):
            commodity_offs.setdefault(cc, [])  # 키워드매칭은 빈 리스트(오프셋 검증 대상 아님을 표시)
    if not commodity_offs:
        return []

    try:
        obs_date = datetime.strptime(f[C_DATE][:8], "%Y%m%d").date().isoformat()
    except ValueError:
        obs_date = None

    tone = _parse_tone(f[C_TONE])
    country = _first_country(f[C_V2LOC])

    out = []
    for cc, offs in commodity_offs.items():
        is_theme_commodity = cc in THEME_COMMODITY.values()
        # is_relevant() 게이트 — CU/NI(전용테마 매칭)도 CO/LI/REE(키워드 매칭)와 동일하게 전 상품·
        # 전 티어 적용(2026-07-20 /goal 재설계). CU/NI의 THEME_RULES 근접성 검증은 "상품 테마와
        # 사건 테마가 같은 문단"만 보장할 뿐 그 문서 자체가 구리/니켈 산업 문서인지는 보장하지
        # 않는다 — 실측(SRS n=200)상 오염 사례 다수가 CU/NI였던 점에서 이 게이트가 필요함.
        if not is_relevant(kw_haystack, cc):
            continue

        # 노이즈(지역 절도·사건사고 등) 배제는 티어 판정 전에 최우선 적용한다.
        # 예전엔 "뉴스" 폴백에서만 걸러서, 절도기사가 우연히 근접성 조건까지 통과하면(예: 인근에
        # 무관한 분쟁성 테마가 같이 태깅) 분쟁/정책 티어로 새어나가는 사례가 실측(2026-07-07)됐다.
        if any(nt in v2themes for nt in NOISE_THEMES):
            continue

        # 근접성 검증된(CU/NI) 또는 2차 신호어 통과한(CO/LI/REE) 테마규칙 매칭 시도
        matched = _theme_rule_for_commodity(theme_offsets, offs)
        if matched:
            event_type, direction, target, severity = matched
            base_conf = 0.5
        else:
            event_type, direction, target = "뉴스", "neutral", "mixed"
            severity, base_conf = _tone_severity(tone)

        conf = base_conf + (0.15 if is_theme_commodity else 0.0)  # 전용코드=신뢰도↑
        out.append(dict(
            event_id=hashlib.md5(f"{doc_id}|{cc}".encode()).hexdigest()[:16],
            doc_id=doc_id, commodity=cc, country=country, event_type=event_type,
            direction=direction, target=target, severity=min(3.0, severity),
            horizon_months=None, obs_date=obs_date, confidence=round(min(1.0, conf), 2),
            evidence_quote=f"[GKG tone={tone}] {f[C_DOCID]}"[:300],
            extractor="rule", provider="gkg", model="gkg-theme-v4", prompt_version="",
            schema_version="1.0",
        ))
    return out


def parse_zip(path: str) -> list[dict]:
    """zip 1개(15분치, 통상 1000~2000행) → 이벤트 dict 리스트."""
    events = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if not names:
            return events
        with z.open(names[0]) as fh:
            for raw in fh:
                try:
                    line = raw.decode("utf-8", errors="ignore")
                except Exception:
                    continue
                events.extend(parse_gkg_row(line))
    return events


# ── 파일 순회·재개·배치 적재 ──────────────────────────────────────────────────
def _state_path(bulk_root: str) -> str:
    p = os.path.join(bulk_root, "_logs", "gkg_parsed.txt")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def _load_state(bulk_root: str) -> set:
    p = _state_path(bulk_root)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def iter_zip_files(bulk_root: str, year_from: int | None, year_to: int | None) -> list[str]:
    out = []
    for yr in sorted(os.listdir(bulk_root)):
        if not yr.isdigit():
            continue
        y = int(yr)
        if year_from and y < year_from:
            continue
        if year_to and y > year_to:
            continue
        yr_dir = os.path.join(bulk_root, yr)
        for fn in sorted(os.listdir(yr_dir)):
            if fn.endswith(".gkg.csv.zip"):
                out.append(os.path.join(yr_dir, fn))
    return out


def run(bulk_root: str, year_from: int | None = 2016, year_to: int | None = None,
        worker: int = 0, workers: int = 1, batch_files: int = 1000) -> dict:
    files = iter_zip_files(bulk_root, year_from, year_to)
    my_files = files[worker::workers]
    done_set = _load_state(bulk_root)
    todo = [p for p in my_files if os.path.basename(p) not in done_set]
    print(f"[gkg_parse] worker={worker}/{workers} 담당 {len(my_files)}건 중 미처리 {len(todo)}건")

    state_path = _state_path(bulk_root)
    batch: list[dict] = []
    newly_done: list[str] = []
    n_events = n_files = 0

    def _flush():
        nonlocal batch, newly_done
        if batch:
            # 대용량 전용 샤드 append(O(batch), 전체 재작성 없음) — append_events()는 이 규모
            # (수십만 파일)에서 매 flush마다 누적 파일 전체를 읽어 재작성해 갈수록 느려지고,
            # 멀티워커 동시 호출 시 서로의 결과를 덮어써 유실됨(2026-07-08 발견·수정).
            store.append_events_sharded(batch)
            n = len(batch)
            batch = []
        else:
            n = 0
        if newly_done:
            with open(state_path, "a", encoding="utf-8") as f:
                f.write("\n".join(newly_done) + "\n")
            newly_done = []
        return n

    for i, path in enumerate(todo, 1):
        try:
            events = parse_zip(path)
        except Exception as e:
            print(f"  [warn] {os.path.basename(path)}: {e}")
            continue
        batch.extend(events)
        newly_done.append(os.path.basename(path))
        n_events += len(events)
        n_files += 1
        if i % batch_files == 0 or i == len(todo):
            _flush()
            print(f"  진행 {i}/{len(todo)} (누적 이벤트 {n_events}건)")

    return {"files": n_files, "events": n_events, "worker": worker}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bulk-root", required=True, help="gkg_bulk_download.py --dest와 동일 경로")
    ap.add_argument("--year-from", type=int, default=2016)
    ap.add_argument("--year-to", type=int, default=None)
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--batch-files", type=int, default=1000, help="N개 파일마다 store에 flush")
    a = ap.parse_args()
    summary = run(a.bulk_root, a.year_from, a.year_to, a.worker, a.workers, a.batch_files)
    print(f"[gkg_parse] 완료: {summary}")
