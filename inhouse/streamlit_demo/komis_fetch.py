"""KOMIS 실시간 조회(fetch) — 2026-08-31 사용자 지시.

사용자가 "요약보고서 데모에서 광물자원가격·핵심광물지도는 fetch 버튼을
추가해서 komis.or.kr에서 데이터를 가져와 KOMIS 데이터 조회 결과에 표시"를
요청했다.

**이 샌드박스의 실제 네트워크 상태(2026-08-31 재확인, 앞선 기록 정정)**:
curl·Playwright는 여전히 komis.or.kr 연결 자체가 타임아웃 난다 — 다만
httpx(이 모듈이 쓰는 클라이언트)는 연결에 성공한다(GET 200 + 유효한
JSESSIONID, POST도 200). 도구별로 이 샌드박스의 아웃바운드 정책이 다르게
적용되는 것으로 보인다. 즉 "이 환경은 komis.or.kr에 못 닿는다"는 이전
기록은 부정확했다 — httpx 기준으로는 실제 데이터까지 왕복 검증했다(아래
"실측 검증" 참고).

**DMZ/inhouse 원칙 예외 승인 근거**: inhouse는 원칙적으로 외부망을 직접
호출하지 않는다(2026-08-06 DMZ/inhouse 분리 설계 — 외부망 호출은
`dmz/geo_collectors`·`dmz/msr_collectors`의 몫). 이 데모가 원칙과 달리
komis.or.kr을 직접 호출하는 것에 대해 사용자에게 직접 확인했고, "이 데모는
납품처에 우리가 만든 기능을 설명하기 위해 만듬. dmz존에 있는것과 같음.
납품후에는 미사용됨"이라는 명시적 승인을 받았다(2026-08-31) — 즉 이 예외는
이 데모 전용이며, 납품 후 폐기를 전제로 한다. 실제 운영 파이프라인
(inhouse/geo, inhouse/mineral_supply_risk 등)에 이 패턴을 그대로 옮기면
안 된다.

**가격기준(srchPrcCrtr) 코드는 하드코딩하지 않는다**: 애초 income_data/komis
덤프(2026-08-26 캡처)에서 뽑은 고정 코드(예: 동=502)로 시도했더니 실제
komis.or.kr이 200 OK에 데이터는 전부 null인 응답을 줬다 — 원인을 파봤더니
같은 광종의 같은 덤프 안에서도 날짜별로 501/502가 다르게 찍혀 있었고, 실측
결과 "현재 유효 코드는 501"이었다(즉 서버가 이 코드를 주기적으로 재발급하는
서로게이트 키). 그래서 가격 조회는 매번 먼저 `getMnrlPriceCrtr`로 그 광종의
"현재" 가격기준 후보 목록을 받아와(LME CASH 라벨이 있으면 그것을, 없으면
목록 첫 항목을 선택) 그 cdKey로 본조회를 하는 2단계 흐름으로 바꿨다 —
34개 희소금속 하드코딩 표도 이 과정에서 통째로 제거했다(코드가 며칠 만에
드리프트하는 게 실측으로 확인됐으므로 정적 표는 곧 썩는다).

price_iron_energy(`/Komis/RsrcPrice/IronOre`)·price_other(`/Komis/RsrcPrice/EtcMnrl`)도
2026-08-31 실측(철=MNRL1011, 금=MNRL0046)으로 base/minor metals와 동일한
`getMnrlPriceCrtr`→`getMnrlPrcByMnrkndUnqCd` 2단계 흐름이 그대로 통함을
확인했다 — 이전 기록("확인 안 됨, fetch 미구현")은 낡은 우려였고 현재는
4개 가격 페이지 전부 fetch를 지원한다.

**실측 검증(2026-08-31)**: 동(MNRL0008)·map_korea·map_mineral 실호출로
실제 가격·거래·매장량 데이터가 돌아오는 것까지 확인했다(단순 200 응답이
아니라 `data.defaultMnrl`/`list`/`data` 안에 실 레코드가 채워진 것을 직접
확인). 리튬(MNRL0001)·코발트(MNRL0003)·갈륨(MNRL0024) 3종은
`getMnrlPriceCrtr` 응답만 확인(본조회까지는 매 실행마다 재확인하지 않음).

⚠ 응답이 HTTP 200 + 유효 JSON이어도 실데이터가 비어 있을 수 있다는 게 이번에
실측으로 드러난 사실이라, `_require_*` 계열 함수로 각 페이지의 실데이터
필드가 비어 있으면 명시적으로 KomisFetchError를 낸다 — "200이면 성공"으로
넘기지 않는다.

⚠ KOMIS AJAX는 "쿠키 동일출처 세션 필요"라고 명세에 명시돼 있다 — 그래서
매 fetch마다 먼저 해당 페이지를 GET해 세션 쿠키를 얻은 뒤, 같은
`httpx.Client` 세션으로 (가격 조회의 경우 `getMnrlPriceCrtr`까지 포함해)
AJAX POST를 보낸다."""
from __future__ import annotations

import calendar
import logging
import os

import httpx

_log = logging.getLogger(__name__)


class KomisFetchError(RuntimeError):
    """실시간 조회 실패(네트워크·타임아웃·예상 못한 응답 shape·빈 데이터 등)."""


def _base_url() -> str:
    return os.getenv("KOMIS_FETCH_BASE_URL", "https://www.komis.or.kr").rstrip("/")


_AJAX_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}


def _open_session(session_page_path: str) -> httpx.Client:
    base = _base_url()
    # 세션 GET 하나 + AJAX POST 1~2개를 이 타임아웃으로 순서대로 호출하므로
    # 최악의 경우 이 값의 2~3배까지 걸린다 — 8초가 아니라 5초로 잡아 시연 중
    # 대기시간을 15초 이내로 묶는다.
    client = httpx.Client(base_url=base, timeout=5.0, headers={"User-Agent": "Mozilla/5.0"})
    try:
        client.get(session_page_path)  # 세션 쿠키 확보(§모듈 docstring)
    except httpx.TimeoutException as exc:
        client.close()
        raise KomisFetchError(
            f"komis.or.kr 연결 시간초과({base}) — 이 환경에서 외부망이 막혀 있을 수 있습니다."
        ) from exc
    except httpx.RequestError as exc:
        client.close()
        raise KomisFetchError(f"komis.or.kr 연결 실패({base}): {exc}") from exc
    return client


def _ajax_post(client: httpx.Client, ajax_path: str, params: dict) -> dict:
    try:
        response = client.post(ajax_path, data=params, headers=_AJAX_HEADERS)
    except httpx.TimeoutException as exc:
        raise KomisFetchError(
            f"komis.or.kr 연결 시간초과({_base_url()}) — 이 환경에서 외부망이 막혀 있을 수 있습니다."
        ) from exc
    except httpx.RequestError as exc:
        raise KomisFetchError(f"komis.or.kr 연결 실패({_base_url()}): {exc}") from exc
    if response.status_code != 200:
        raise KomisFetchError(f"komis.or.kr 예상치 못한 응답({response.status_code})")
    try:
        return response.json()
    except ValueError as exc:
        raise KomisFetchError("komis.or.kr 응답이 JSON이 아닙니다(세션 만료·차단 가능성).") from exc


def _post(session_page_path: str, ajax_path: str, params: dict) -> dict:
    client = _open_session(session_page_path)
    try:
        return _ajax_post(client, ajax_path, params)
    finally:
        client.close()


def _pick_price_criterion(candidates: list[dict], mineral_code: str) -> dict:
    if not candidates:
        raise KomisFetchError(
            f"komis.or.kr에서 '{mineral_code}'의 가격기준 목록을 받아오지 못했습니다(빈 응답)."
        )
    for candidate in candidates:
        if "LME CASH" in str(candidate.get("cdVal", "")).upper():
            return candidate
    return candidates[0]


def _require_defaultMnrl(result: dict, mineral_code: str) -> dict:
    if not (result.get("data") or {}).get("defaultMnrl"):
        raise KomisFetchError(
            f"komis.or.kr 응답은 받았지만 '{mineral_code}' 가격 데이터가 비어 있습니다"
            "(가격기준 코드가 그새 갱신됐을 수 있습니다 — 잠시 후 다시 시도해보세요)."
        )
    return result


def _require_list(result: dict, mineral_code: str) -> dict:
    if not result.get("list"):
        raise KomisFetchError(f"komis.or.kr 응답은 받았지만 '{mineral_code}' 데이터가 비어 있습니다.")
    return result


def _require_data(result: dict, mineral_code: str) -> dict:
    if not result.get("data"):
        raise KomisFetchError(f"komis.or.kr 응답은 받았지만 '{mineral_code}' 데이터가 비어 있습니다.")
    return result


# ── price_base_metals ────────────────────────────────────────────────
# 실측: 광종별 현재 유효 srchPrcCrtr는 고정이 아니라 getMnrlPriceCrtr로
# 매번 조회해야 한다(§모듈 docstring — 501/502 드리프트 실측). 6개 광종
# 자체 목록(니켈/동/아연/알루미늄/연/주석)은 income_data/komis 덤프 기준.
BASE_METALS_CODES = {"MNRL0002", "MNRL0008", "MNRL0023", "MNRL0009", "MNRL0022", "MNRL0016"}


# 2026-08-31 사용자 지시(평균옵션·기간구분자 UI 추가): 라이브 실측으로 확인한
# 값들 — srchAvgOpt는 DAY/WEEK/MONTH/QUARTER/YEAR(사용자가 부른 "QUATER"는
# 실제 KOMIS 값이 아니다, QUARTER가 맞다 — QUATER로 보내면 0건). srchField=
# "month"는 yyyy-mm이 아니라 하이픈 뺀 yyyymm이어야 데이터가 나온다(yyyy-mm은
# 0건 실측 확인) — 그래서 UI 입력(yyyy-mm)과 실제 전송 형식을 분리한다.
VALID_AVG_OPTS = {"DAY", "WEEK", "MONTH", "QUARTER", "YEAR"}
VALID_PERIOD_FIELDS = {"year", "month"}


def _period_arg(period_field: str, value: str) -> str:
    """UI 입력(년간=yyyy, 월간=yyyy-mm)을 KOMIS 실제 전송 형식으로 변환."""
    if period_field == "month":
        return value.replace("-", "")
    return value


def _resolve_compare_criterion(
    client: httpx.Client, hp000: str, compare_mineral_code: str | None, *, category_label: str
) -> tuple[str, str]:
    """비교 광종의 가격기준(cdKey)을 조회한다 — §fetch_price_minor_metals
    2026-08-31 버그수정과 동일 패턴(주 광종처럼 비교 광종도 getMnrlPriceCrtr로
    매번 조회해야 한다, 하드코딩 불가). 없으면 ("", "[선택]")로 "비교 안 함"."""
    if not compare_mineral_code:
        return "", "[선택]"
    compare_crtr_data = _ajax_post(
        client, "/Komis/RsrcPrice/ajax/getMnrlPriceCrtr", {"HP000": hp000, "mnrkndUnqCd": compare_mineral_code}
    )
    compare_candidates = compare_crtr_data.get("data") or []
    if not compare_candidates:
        raise KomisFetchError(
            f"비교 광종 '{compare_mineral_code}'는 komis.or.kr {category_label} 가격기준 목록에 없습니다 — "
            "비교 광종을 다시 선택하거나 비워두세요."
        )
    compare_crtr = _pick_price_criterion(compare_candidates, compare_mineral_code)
    return compare_mineral_code, str(compare_crtr["cdKey"])


def fetch_price_base_metals(
    mineral_code: str, *,
    avg_opt: str = "DAY", period_field: str = "year",
    start_period: str = "2000", end_period: str = "2026",
    compare_mineral_code: str | None = None,
) -> dict:
    if mineral_code not in BASE_METALS_CODES:
        raise KomisFetchError(
            f"'{mineral_code}'는 비철금속 6종(니켈/동/아연/알루미늄/연/주석)이 아닙니다 — 광종을 다시 선택하세요."
        )
    if avg_opt not in VALID_AVG_OPTS or period_field not in VALID_PERIOD_FIELDS:
        raise KomisFetchError(f"평균 옵션('{avg_opt}') 또는 기간 구분자('{period_field}') 값이 올바르지 않습니다.")
    client = _open_session("/Komis/RsrcPrice/BaseMetals")
    try:
        crtr_data = _ajax_post(
            client, "/Komis/RsrcPrice/ajax/getMnrlPriceCrtr", {"HP000": "HP001", "mnrkndUnqCd": mineral_code}
        )
        crtr = _pick_price_criterion(crtr_data.get("data") or [], mineral_code)
        compare_mnrknd_cd, compare_prc_crtr = _resolve_compare_criterion(
            client, "HP001", compare_mineral_code, category_label="비철금속"
        )
        params = {
            "mnrkndUnqRadioCd": mineral_code, "srchMnrkndUnqCd": mineral_code,
            "srchPrcCrtr": str(crtr["cdKey"]), "srchAvgOpt": avg_opt, "srchField": period_field,
            "srchStartDate": _period_arg(period_field, start_period),
            "srchEndDate": _period_arg(period_field, end_period),
            "srchCompareMnrkndUnqCd": compare_mnrknd_cd, "srchComparePrcCrtr": compare_prc_crtr, "lmeInvt": "Y",
        }
        result = _ajax_post(client, "/Komis/RsrcPrice/ajax/getMnrlPrcByMnrkndUnqCd", params)
    finally:
        client.close()
    return _require_defaultMnrl(result, mineral_code)


# ── price_minor_metals ───────────────────────────────────────────────
# 2026-08-31 버그수정(사용자 지적 — "비교 광종 있는/없는 보고서가 전혀
# 다르지 않다"): 이 함수가 `compare_mineral_code`를 아예 안 받아서
# `srchCompareMnrkndUnqCd`/`srchComparePrcCrtr`가 항상 빈 값("[선택]")으로
# 나갔다 — UI에서 비교 광종을 뭘 골라도 komis.or.kr 응답의 `compareMnrl`이
# 항상 빈 배열이라, report_gen이 받는 `komis_response`엔 비교 데이터
# 자체가 없었다(report_gen 쪽 compare_series 파싱·근거생성·검증 로직은
# 정상이었음 — 문제는 순수히 이 fetch 함수가 비교 광종의 가격기준을
# 조회해 요청에 실어 보내지 않은 것). 주 광종과 동일하게
# `getMnrlPriceCrtr`로 비교 광종의 "현재" 가격기준도 따로 조회해야 한다
# (§모듈 docstring — 가격기준은 날짜별로 드리프트하는 서로게이트 키라
# 하드코딩 불가, 비교 광종도 예외 아님).
def fetch_price_minor_metals(
    mineral_code: str,
    *,
    avg_opt: str = "DAY",
    period_field: str = "year",
    start_period: str = "2000",
    end_period: str = "2026",
    compare_mineral_code: str | None = None,
) -> dict:
    if avg_opt not in VALID_AVG_OPTS or period_field not in VALID_PERIOD_FIELDS:
        raise KomisFetchError(f"평균 옵션('{avg_opt}') 또는 기간 구분자('{period_field}') 값이 올바르지 않습니다.")
    client = _open_session("/Komis/RsrcPrice/MinorMetals")
    try:
        crtr_data = _ajax_post(
            client, "/Komis/RsrcPrice/ajax/getMnrlPriceCrtr", {"HP000": "HP002", "mnrkndUnqCd": mineral_code}
        )
        candidates = crtr_data.get("data") or []
        if not candidates:
            raise KomisFetchError(
                f"'{mineral_code}'는 komis.or.kr 희소금속 가격기준 목록에 없습니다 — 수동 붙여넣기를 이용하세요."
            )
        crtr = _pick_price_criterion(candidates, mineral_code)
        compare_mnrknd_cd = ""
        compare_prc_crtr = "[선택]"
        if compare_mineral_code:
            compare_crtr_data = _ajax_post(
                client, "/Komis/RsrcPrice/ajax/getMnrlPriceCrtr",
                {"HP000": "HP002", "mnrkndUnqCd": compare_mineral_code},
            )
            compare_candidates = compare_crtr_data.get("data") or []
            if not compare_candidates:
                raise KomisFetchError(
                    f"비교 광종 '{compare_mineral_code}'는 komis.or.kr 희소금속 가격기준 목록에 없습니다 — "
                    "비교 광종을 다시 선택하거나 비워두세요."
                )
            compare_crtr = _pick_price_criterion(compare_candidates, compare_mineral_code)
            compare_mnrknd_cd = compare_mineral_code
            compare_prc_crtr = str(compare_crtr["cdKey"])
        params = {
            "srchMnrkndUnqCd": mineral_code, "srchPrcCrtr": str(crtr["cdKey"]), "spcfct": crtr.get("spcfct", ""),
            "srchAvgOpt": avg_opt, "srchField": period_field,
            "srchStartDate": _period_arg(period_field, start_period),
            "srchEndDate": _period_arg(period_field, end_period),
            "srchCompareMnrkndUnqCd": compare_mnrknd_cd, "srchComparePrcCrtr": compare_prc_crtr,
        }
        result = _ajax_post(client, "/Komis/RsrcPrice/ajax/getMnrlPrcByMnrkndUnqCd", params)
    finally:
        client.close()
    return _require_defaultMnrl(result, mineral_code)


# ── price_iron_energy / price_other ──────────────────────────────────
# 2026-08-31 실측(사용자 지시로 §모듈 docstring 36번줄의 "확인 안 됨" 우려
# 재검증): IronOre(철/MNRL1011)·EtcMnrl(금/MNRL0046) 세션으로
# getMnrlPriceCrtr→getMnrlPrcByMnrkndUnqCd 2단계를 직접 호출해 실 데이터
# 응답까지 확인 — base/minor metals와 동일한 흐름이 그대로 통한다.
def fetch_price_iron_energy(
    mineral_code: str, *,
    avg_opt: str = "DAY", period_field: str = "year",
    start_period: str = "2000", end_period: str = "2026",
    compare_mineral_code: str | None = None,
) -> dict:
    if avg_opt not in VALID_AVG_OPTS or period_field not in VALID_PERIOD_FIELDS:
        raise KomisFetchError(f"평균 옵션('{avg_opt}') 또는 기간 구분자('{period_field}') 값이 올바르지 않습니다.")
    client = _open_session("/Komis/RsrcPrice/IronOre")
    try:
        crtr_data = _ajax_post(
            client, "/Komis/RsrcPrice/ajax/getMnrlPriceCrtr", {"HP000": "HP003", "mnrkndUnqCd": mineral_code}
        )
        candidates = crtr_data.get("data") or []
        if not candidates:
            raise KomisFetchError(
                f"'{mineral_code}'는 komis.or.kr 철광석·에너지 가격기준 목록에 없습니다 — 수동 붙여넣기를 이용하세요."
            )
        crtr = _pick_price_criterion(candidates, mineral_code)
        compare_mnrknd_cd, compare_prc_crtr = _resolve_compare_criterion(
            client, "HP003", compare_mineral_code, category_label="철광석·에너지"
        )
        params = {
            "mnrkndUnqRadioCd": mineral_code, "srchMnrkndUnqCd": mineral_code,
            "srchPrcCrtr": str(crtr["cdKey"]), "srchAvgOpt": avg_opt, "srchField": period_field,
            "srchStartDate": _period_arg(period_field, start_period),
            "srchEndDate": _period_arg(period_field, end_period),
            "srchCompareMnrkndUnqCd": compare_mnrknd_cd, "srchComparePrcCrtr": compare_prc_crtr,
        }
        result = _ajax_post(client, "/Komis/RsrcPrice/ajax/getMnrlPrcByMnrkndUnqCd", params)
    finally:
        client.close()
    return _require_defaultMnrl(result, mineral_code)


def fetch_price_other(
    mineral_code: str, *,
    avg_opt: str = "DAY", period_field: str = "year",
    start_period: str = "2000", end_period: str = "2026",
    compare_mineral_code: str | None = None,
) -> dict:
    if avg_opt not in VALID_AVG_OPTS or period_field not in VALID_PERIOD_FIELDS:
        raise KomisFetchError(f"평균 옵션('{avg_opt}') 또는 기간 구분자('{period_field}') 값이 올바르지 않습니다.")
    client = _open_session("/Komis/RsrcPrice/EtcMnrl")
    try:
        crtr_data = _ajax_post(
            client, "/Komis/RsrcPrice/ajax/getMnrlPriceCrtr", {"HP000": "HP004", "mnrkndUnqCd": mineral_code}
        )
        candidates = crtr_data.get("data") or []
        if not candidates:
            raise KomisFetchError(
                f"'{mineral_code}'는 komis.or.kr 기타 광종 가격기준 목록에 없습니다 — 수동 붙여넣기를 이용하세요."
            )
        crtr = _pick_price_criterion(candidates, mineral_code)
        compare_mnrknd_cd, compare_prc_crtr = _resolve_compare_criterion(
            client, "HP004", compare_mineral_code, category_label="기타"
        )
        params = {
            "mnrkndUnqRadioCd": mineral_code, "srchMnrkndUnqCd": mineral_code,
            "srchPrcCrtr": str(crtr["cdKey"]), "srchAvgOpt": avg_opt, "srchField": period_field,
            "srchStartDate": _period_arg(period_field, start_period),
            "srchEndDate": _period_arg(period_field, end_period),
            "srchCompareMnrkndUnqCd": compare_mnrknd_cd, "srchComparePrcCrtr": compare_prc_crtr,
        }
        result = _ajax_post(client, "/Komis/RsrcPrice/ajax/getMnrlPrcByMnrkndUnqCd", params)
    finally:
        client.close()
    return _require_defaultMnrl(result, mineral_code)


# ── map_korea / map_global ───────────────────────────────────────────
# 실측: 이 세션이 Phase3에서 캡처해둔 실제 응답(요청 파라미터가 그대로
# echo돼 있음) — komis_raw.py의 map_korea/map_global example_raw_json과
# 같은 원천(MNRL0024=갈륨, 2026-01-01~12-31 조회).
# 2026-08-31 사용자 지시: 대한민국 수급지도(map_korea)에 기간 구분자(년/월)·
# 국가명 직접입력·생산품 유형(Lv3)·HS코드(Lv5) 구분자 추가 — komis.or.kr
# 페이지 JS(`_komis_common.js`)를 직접 읽어 실측 확인한 4단계 계층
# (광종→생산품유형(Lv3)→물질흐름세부(Lv4)→HSCode(Lv5))와 국가 목록 엔드포인트:
# - `/ajax/komiscommon/getListMttrFlow`(POST srchMnrkndUnqCd·srchMttrFlowCd·
#   openYn) — srchMttrFlowCd가 비면 Lv3(생산품 유형), 있으면 그 하위 Lv4
#   (물질흐름세부) 목록을 준다. 사용자가 이름 붙인 "생산품 유형 구분자"가
#   바로 이 Lv3(`[생산품 유형 전체]` 라벨을 JS에서 직접 확인).
# - `/ajax/komiscommon/getListOnlyHsCode`(POST srchMnrkndUnqCd·srchMttrFlowCd·
#   srchMttrFlowDtlCd·isFront) — HSCode(Lv5) 목록. 실측 확인: Lv3/Lv4가
#   비어 있어도 서버는 그 광종의 전체 HS코드 목록을 그대로 준다(KOMIS
#   자체 화면은 Lv3 미선택이면 UI만 숨기는 것뿐, 서버 제약이 아니다) — 이
#   데모는 사용자가 명시한 2단계(생산품유형·HS코드)만 노출하고 Lv4는 항상
#   비워 보낸다.
# - `/ajax/common/getNatInfoCodeList`(POST cdType=koNtnCd) — 국가 232종
#   {cdVal:한글명, cdKey:코드}. 사용자가 "국가명 입력"이라고 해서 코드가
#   아니라 한글명을 직접 입력받고, fetch_map_korea가 이 목록에서 매칭되는
#   코드를 찾아 srchNtnCd로 변환한다(가격기준 코드 리졸브와 같은 패턴).
def fetch_product_type_options(mineral_code: str, parent_code: str = "") -> list[dict]:
    """생산품 유형(Lv3, parent_code="")·물질흐름세부(Lv4, parent_code=Lv3코드)
    목록 — [{mttrFlowCd, mttrFlowNm}, ...]."""
    client = _open_session("/Komis/MnrlMap/Korea")
    try:
        data = _ajax_post(
            client, "/ajax/komiscommon/getListMttrFlow",
            {"srchMnrkndUnqCd": mineral_code, "srchMttrFlowCd": parent_code, "openYn": "Y"},
        )
    finally:
        client.close()
    return data.get("data") or []


def fetch_hs_code_options(mineral_code: str, product_type_code: str = "") -> list[dict]:
    """HSCode(Lv5) 목록 — [{hsCd, itemNm}, ...]. Lv4는 항상 비워 보낸다(§위
    모듈 주석 — 서버는 Lv3만으로도 전체 하위 HS코드를 돌려준다)."""
    client = _open_session("/Komis/MnrlMap/Korea")
    try:
        data = _ajax_post(
            client, "/ajax/komiscommon/getListOnlyHsCode",
            {
                "srchMnrkndUnqCd": mineral_code, "srchMttrFlowCd": product_type_code,
                "srchMttrFlowDtlCd": "", "isFront": "Y",
            },
        )
    finally:
        client.close()
    return data.get("data") or []


def _resolve_country_code(client: httpx.Client, country_name: str) -> str:
    if not country_name.strip():
        return ""
    data = _ajax_post(client, "/ajax/common/getNatInfoCodeList", {"cdType": "koNtnCd"})
    for row in data.get("data") or []:
        if row.get("cdVal") == country_name.strip():
            return row.get("cdKey", "")
    raise KomisFetchError(
        f"'{country_name}'에 해당하는 국가를 komis.or.kr 국가 목록에서 찾지 못했습니다 — "
        "정확한 한글 국가명을 입력하세요(예: 중국)."
    )


def _map_korea_date_bounds(period_field: str, start_period: str, end_period: str) -> tuple[str, str]:
    """UI 입력(년간=yyyy, 월간=yyyy-mm)을 KOMIS가 받는 yyyymmdd로 변환 —
    시작은 그 기간의 1일, 종료는 그 기간의 마지막 날."""
    if period_field == "month":
        start_y, start_m = start_period.split("-")
        end_y, end_m = end_period.split("-")
        last_day = calendar.monthrange(int(end_y), int(end_m))[1]
        return f"{start_y}{start_m}01", f"{end_y}{end_m}{last_day:02d}"
    return f"{start_period}0101", f"{end_period}1231"


def fetch_map_korea(
    mineral_code: str, *, trade_direction: str = "import",
    period_field: str = "year", start_period: str = "2025", end_period: str = "2025",
    country_name: str = "", product_type_code: str = "", hs_code: str = "",
) -> dict:
    start_date, end_date = _map_korea_date_bounds(period_field, start_period, end_period)
    if period_field == "month":
        sy, sm = start_period.split("-")
        ey, em = end_period.split("-")
        prev_start_date, prev_end_date = _map_korea_date_bounds(
            period_field, f"{int(sy) - 1}-{sm}", f"{int(ey) - 1}-{em}"
        )
    else:
        prev_start_date, prev_end_date = _map_korea_date_bounds(
            period_field, str(int(start_period) - 1), str(int(end_period) - 1)
        )
    client = _open_session("/Komis/MnrlMap/Korea")
    try:
        country_code = _resolve_country_code(client, country_name)
        params = {
            "srchNtnCd": country_code, "srchDateE": end_date, "orderSort": "DESC",
            "srchMttrFlowDtlCd": "", "srchIncmExp": "I" if trade_direction == "import" else "E",
            "srchHsCd": hs_code, "orderBy": "realPrdctnQuty1", "srchMnrkndUnqCd": mineral_code,
            "listCount": "10", "srchDatePE": prev_end_date, "srchMttrFlowCd": product_type_code,
            "srchDateS": start_date, "page": "1", "srchTypeAW": "A",
            "srchCrtrYmd": "Y" if period_field == "year" else "M",
            "srchDatePS": prev_start_date,
        }
        result = _ajax_post(client, "/Komis/MnrlMap/MapKorea/ajax/getListKoreaData", params)
    finally:
        client.close()
    return _require_list(result, mineral_code)


def fetch_map_global(
    mineral_code: str, *,
    start_date: str = "20260101", end_date: str = "20261231",
    prev_start_date: str = "20250101", prev_end_date: str = "20251231",
    chart_start_date: str = "20220101", chart_end_date: str = "20261231",
) -> dict:
    params = {
        "srchDateE": end_date, "orderSort": "DESC", "srchMttrFlowDtlCd": "",
        "srchExpNtnCd": "", "srchDateChartE": chart_end_date, "srchHsCd": "",
        "orderBy": "", "srchMnrkndUnqCd": mineral_code, "listCount": "15",
        "srchDatePE": prev_end_date, "srchMttrFlowCd": "", "srchDateS": start_date,
        "srchIncmNtnCd": "", "srchDateChartS": chart_start_date, "page": "1",
        "srchTypeAW": "A", "srchCrtrYmd": "Y", "srchDatePS": prev_start_date,
    }
    result = _post("/Komis/MnrlMap/Nation", "/Komis/MnrlMap/MapNation/ajax/getListDataNation", params)
    return _require_list(result, mineral_code)


# ── map_mineral ───────────────────────────────────────────────────────
# 실측: report-summary-agent가 income_data/komis/komis_08_mineral_map.json
# results[].params에서 확인해 전달(2026-08-31) — 이 페이지는 KOMIS가 동시에
# 3개 엔드포인트를 쏜다(전부 같은 파라미터 shape): getListMapMnrlChartData
# (연도별 시계열)·getListMapMnrlData(단일연도 국가별 스냅샷)·
# getListMnrlTablePrdctnBurgudg(국가별 최근5개년+비중표). report_gen이
# 각각 komis_response/komis_snapshot_response/komis_share_response 3개
# 필드로 따로 받는다(계약: documents/산출물/2026-W36_0831-0906/
# report_gen_광물지도_2개엔드포인트_추가_260831.md).
# ⚠ snapshot(getListMapMnrlData)은 단일 연도 전제 — 다년 범위로 조회하면
# KOMIS가 그 범위 전체를 합산한 값을 준다(report-summary-agent 실측
# 확인). report_gen이 라벨링에 쓰는 "최신연도"와 맞추기 위해 항상
# end_year 하나만으로(srchDateS=srchDateE=end_year) 조회한다.
def fetch_map_mineral(
    mineral_code: str, *, measure: str = "reserves", start_year: str = "2021", end_year: str = "2025"
) -> dict:
    selected_tab = "burudg" if measure == "reserves" else "prdctn"
    range_params = {
        "srchMnrkndUnqCd": mineral_code, "srchMnrkndSeCd": "", "srchNtnCd": "",
        "srchDateS": start_year, "srchDateE": end_year,
        "selectedTab": selected_tab, "srchNtnEngCd": "",
    }
    snapshot_params = {**range_params, "srchDateS": end_year, "srchDateE": end_year}
    client = _open_session("/Komis/MnrlMap/MnrlMap")
    try:
        chart = _ajax_post(client, "/Komis/MnrlMap/MapMnrl/ajax/getListMapMnrlChartData", range_params)
        snapshot = _ajax_post(client, "/Komis/MnrlMap/MapMnrl/ajax/getListMapMnrlData", snapshot_params)
        share = _ajax_post(client, "/Komis/MnrlMap/MapMnrl/ajax/getListMnrlTablePrdctnBurgudg", range_params)
    finally:
        client.close()
    _require_data(chart, mineral_code)
    return {"chart": chart, "snapshot": snapshot, "share": share}


# 2026-08-31: 평균옵션/기간구분자/기간(**period_kwargs)을 report_demo.py의
# 실시간 조회 옵션 UI에서 넘겨받아 그대로 관통시킨다 — avg_opt/period_field/
# start_period/end_period가 이 kwargs로 들어온다. map_* dispatch는 이 옵션이
# 없어(KOMIS 화면 자체에 없음) 건드리지 않는다.
def _dispatch_price_base_metals(payload: dict, **period_kwargs) -> dict:
    return fetch_price_base_metals(
        payload["mineral"], compare_mineral_code=payload.get("compare_mineral") or None, **period_kwargs
    )


def _dispatch_price_minor_metals(payload: dict, **period_kwargs) -> dict:
    # 2026-08-31: compare_mineral을 fetch 함수까지 관통시킨다(위 버그수정 참고) —
    # 이게 없으면 UI에서 비교 광종을 골라도 komis.or.kr 요청에 실리지 않는다.
    return fetch_price_minor_metals(
        payload["mineral"], compare_mineral_code=payload.get("compare_mineral") or None, **period_kwargs
    )


def _dispatch_price_iron_energy(payload: dict, **period_kwargs) -> dict:
    return fetch_price_iron_energy(
        payload["mineral"], compare_mineral_code=payload.get("compare_mineral") or None, **period_kwargs
    )


def _dispatch_price_other(payload: dict, **period_kwargs) -> dict:
    return fetch_price_other(
        payload["mineral"], compare_mineral_code=payload.get("compare_mineral") or None, **period_kwargs
    )


def _dispatch_map_korea(payload: dict, **period_kwargs) -> dict:
    return fetch_map_korea(
        payload["mineral"], trade_direction=payload.get("trade_direction", "import"), **period_kwargs
    )


def _dispatch_map_global(payload: dict) -> dict:
    return fetch_map_global(payload["mineral"])


def _dispatch_map_mineral(payload: dict, **period_kwargs) -> dict:
    # 2026-08-31 사용자 지시: 광물지도(매장량/생산량) 기간조회(연간, 2021~2025)
    # 추가 — report_demo.py가 start_year/end_year를 넘겨준다.
    return fetch_map_mineral(payload["mineral"], measure=payload.get("measure", "reserves"), **period_kwargs)


# report_demo.py가 page_id만으로 알맞은 fetch 함수를 고를 수 있게 하는 진입점.
KOMIS_FETCH_DISPATCH = {
    "price_base_metals": _dispatch_price_base_metals,
    "price_minor_metals": _dispatch_price_minor_metals,
    "price_iron_energy": _dispatch_price_iron_energy,
    "price_other": _dispatch_price_other,
    "map_korea": _dispatch_map_korea,
    "map_global": _dispatch_map_global,
    "map_mineral": _dispatch_map_mineral,
}
