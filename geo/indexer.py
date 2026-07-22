# -*- coding: utf-8 -*-
"""[3] 지수 산출(순수 결정론): geo_events → 광종별 주/월 지정학 위기 지수.
index = normalize( Σ severity × source_reliability × supply_concentration × sign(direction) )
"""
import numpy as np
import pandas as pd
from . import config as C, store
from .schema import IndexConfig


def _reliability_map() -> dict:
    s = C.load_yaml("sources.yaml") or {}
    return {k: float(v) for k, v in (s.get("reliability") or {}).items()}


def _concentration_map() -> dict:
    s = C.load_yaml("sources.yaml") or {}
    # {"NI:Indonesia": 1.5, "REE:China": 1.8, ...}
    return {k: float(v) for k, v in (s.get("supply_concentration") or {}).items()}


def _load_refdata():
    """USGS refdata(연도별) 로드. 반환 (conc_df, hhi_df) 또는 (None,None)."""
    import os
    rd = C.CONFIG / "refdata"
    cf, hf = rd / "concentration.parquet", rd / "hhi.parquet"
    conc = pd.read_parquet(cf) if os.path.exists(cf) else None
    hhi = pd.read_parquet(hf) if os.path.exists(hf) else None
    return conc, hhi


def _load_kr_share():
    """한국 수입의존 비중(연도별, build_kr_import_share.py 산출) — 없으면 None(가중 생략)."""
    import os
    f = C.CONFIG / "refdata" / "kr_import_share.parquet"
    return pd.read_parquet(f) if os.path.exists(f) else None


def _apply_kr_exposure(ev: pd.DataFrame) -> pd.DataFrame:
    """이중 노출 가중(2026-07-15, 외부감사 B-1① — '한국의' 지수화).
    w = 공급충격 크기(conc, USGS 생산점유) × 한국 직접 노출(s_imp, 관세청 수입비중).
    · s_imp는 (광종,국가,연도) 최근접 연도 매칭, 미매칭(비수입국·자유텍스트 지명)은 0.
    · imp_mult = (1+s_imp)를 광종별 이벤트 모집단 mean-one으로 정규화 — 광종 지수의
      스케일(P90 앵커 동결)을 보존하면서 국가 간 상대 가중만 바꾼다(순수 곱 w=s_prod×s_imp는
      비수입 생산국 이벤트를 0으로 만들어 글로벌 가격 전달경로를 지움 — 채택하지 않음).
    """
    share = _load_kr_share()
    if share is None or "country" not in ev.columns:
        ev["imp_mult"] = 1.0
        return ev
    # 연도 그리드 전개(관측연도 밖은 최근접 연도값 유지) 후 벡터 병합 — 1.8M행에 apply 금지
    yrs = range(int(share["year"].min()), int(ev["yr"].max()) + 1)
    grid = (share.set_index("year").groupby(["commodity", "country"])["imp_share"]
            .apply(lambda s: s.reindex(yrs).ffill().bfill()).reset_index())
    ev = ev.merge(grid.rename(columns={"year": "yr", "imp_share": "s_imp"}),
                  on=["commodity", "country", "yr"], how="left")
    ev["s_imp"] = ev["s_imp"].fillna(0.0)
    raw = 1.0 + ev["s_imp"]
    ev["imp_mult"] = raw / raw.groupby(ev["commodity"]).transform("mean")
    n_hit = int((ev["s_imp"] > 0).sum())
    stat = ev[ev["s_imp"] > 0].groupby("commodity")["imp_mult"].max().round(2).to_dict()
    print(f"  [index] 이중 노출 가중: 수입국 매칭 {n_hit:,}건({n_hit/len(ev):.1%}), "
          f"광종별 최대 배수 {stat}")
    return ev


def _asof_weight(q, yr, valcol):
    """이미 (commodity[,country])로 필터링된 q에서, 이벤트 시점(yr) '당시 이미 발표돼
    있던' USGS 릴리스(release<=yr)만 사용해 as-of 조인(시점정합성 수정 #8, 2026-07-22).
    기존에는 연도가 가장 가까운 값을 릴리스 구분 없이 가져왔는데, refdata.py가
    (commodity,country,year)를 "최신 릴리스값 우선"으로 collapse하고 있어 훗날 개정된
    생산치가 과거 이벤트 채점에 역주입되는 lookahead bias였음. 해당 광종의 최초 USGS
    릴리스보다 이른 이벤트는 그 이상 과거로 갈 데이터가 없으므로 최초 릴리스로 폴백."""
    if len(q) == 0:
        return None
    asof = q[q["release"] <= yr]
    fallback = len(asof) == 0
    if fallback:
        asof = q                           # 해당 광종 첫 릴리스보다 이른 이벤트 — 불가피한 폴백
    asof = asof.assign(_d=(asof["year"] - yr).abs())
    # release<=yr 구간에서는 "이미 발표된 것 중 가장 최신"(release 큰 값 우선) —
    # 폴백 구간에서는 반대로 "가장 이른 릴리스"(release 작은 값 우선)를 골라 lookahead를
    # 최소화한다. 동률 tie-break 방향을 fallback 여부로 뒤집어야 함(2026-07-22 as-of 조인
    # 검증 중 발견 — 처음엔 항상 release 큰 값을 우선해 폴백 시에도 개정치를 끌어오는
    # 잔여 lookahead가 있었음).
    asof = asof.sort_values(["_d", "release"], ascending=[True, fallback])
    return float(asof.iloc[0][valcol])


def _asof_grid(df, keycols, valcol, years):
    """as-of 조인을 이벤트 단위(수십만~수백만 행)로 row-wise apply하면 프로덕션 규모에서
    너무 느림(2026-07-22 실측: 120만 건에서 10분 넘게 미종료) — (commodity[,country]) ×
    연도의 작은 조합(수백 행)에서만 미리 계산한 뒤 이벤트 쪽은 벡터화 merge로 붙인다.
    반환: keycols + ["yr", valcol] 컬럼의 lookup 테이블."""
    if df is None:
        return None
    keys = df[keycols].drop_duplicates()
    rows = []
    for _, k in keys.iterrows():
        q = df
        for c in keycols:
            q = q[q[c] == k[c]]
        for yr in years:
            v = _asof_weight(q, yr, valcol)
            if v is not None:
                rows.append({**k.to_dict(), "yr": yr, valcol: v})
    return pd.DataFrame(rows, columns=keycols + ["yr", valcol])


def _normalize(series: pd.Series, how: str, scale_k: float = 10.0) -> pd.Series:
    import numpy as np
    if how == "tanh0_100":
        # 절대 스케일 유계 변환: 과거 지수가 새 데이터로 재척도되지 않음(발행값 불변).
        # raw=0(이벤트 없음)→50, 심각(raw≈scale_k)→~88, 강한 호재(raw<0)→<50.
        return 50 + 50 * np.tanh(series.astype(float) / float(scale_k))
    if how == "zscore":
        sd = series.std(ddof=0)
        return (series - series.mean()) / sd if sd else series * 0
    # (구) minmax: 자기 히스토리 재척도 결함 — 하위호환용으로만 유지
    lo, hi = series.min(), series.max()
    return (series - lo) / (hi - lo) * 100 if hi > lo else series * 0 + 50


def compute(volume_norm: bool = True, score_formula: str = "mult") -> pd.DataFrame:
    """volume_norm=False는 B-5(피드백기반_수정플랜 P2) 검증 전용 — 미디어 볼륨 드리프트
    정규화 단계를 건너뛴다. score_formula는 B-3 검증 전용 — 'mult'(기본, 현재 프로덕션과
    동일)/'sum'(가중합)/'loggeo'(로그기하평균). 두 파라미터 모두 기본값은 프로덕션 동작과
    완전히 동일(파라미터 추가 전과 바이트 단위로 동일한 출력)."""
    ev = store.load_events()
    if len(ev) == 0:
        print("[index] 이벤트 없음"); return pd.DataFrame()
    # DB 모드(GEO_EVENT_SOURCE=db)에서는 publish가 이미 source를 실어 보냄 — 그때는 manifest
    # 병합을 스킵(병합하면 source_x/source_y 충돌). 파일 모드에서만 manifest에서 붙인다.
    if "source" not in ev.columns:
        man = store.load_manifest()[["doc_id", "source"]].drop_duplicates("doc_id")
        ev = ev.merge(man, on="doc_id", how="left")
    # GKG 이벤트는 ingest→manifest를 거치지 않아(gkg_parse.py가 store에 직접 append) source가
    # 항상 NaN → 아래서 fillna(1.0)로 조용히 기본 신뢰도가 적용되어 sources.yaml의 GDELT 가중치가
    # 무시되는 문제가 있었음(2026-07-06 발견). provider 기준으로 보정.
    if "provider" in ev.columns:
        ev["source"] = ev["source"].fillna(ev["provider"].map({"gkg": "GDELT"}))
    # gkg_verify 재검증 통과분은 provider가 LLM provider(openai_compat 등)로 바뀌어 위 매핑을
    # 빠져나감(2026-07-08 발견) — manifest 미매칭(=GKG 유래뿐: 문서·gnews·gdelt collector는 전부
    # inbox→manifest 경유)인 잔여 NaN은 전부 GDELT로 귀속해 0.7 가중을 보존한다.
    ev["source"] = ev["source"].fillna("GDELT")

    # GKG "뉴스"(규칙기반 폴백 티어) 제외 — 실측(2026-07-06) 확인: 오프셋 근접성·2차 신호어 게이트를
    # 거친 뒤에도 이 티어는 GDELT 자체의 테마 오귀속(예: "구리"가 맥주 브루잉 설비·동전 등과 혼동,
    # 채굴 관련 테마가 동반돼도 실제로는 광산주 내부자거래 공시처럼 무관한 경우 다수)으로 정밀도가
    # 낮게 남는다. 제재/분쟁/정책/재해로 분류된 건(오프셋 근접성 검증됨)과 gkg_verify.py로 LLM
    # 재검증을 거쳐 extractor="llm"이 된 건만 지수에 반영한다.
    if "provider" in ev.columns and "extractor" in ev.columns:
        gkg_news_noise = (ev["provider"] == "gkg") & (ev["extractor"] == "rule") & (ev["event_type"] == "뉴스")
        n_excl = int(gkg_news_noise.sum())
        if n_excl:
            print(f"  [index] GKG 규칙기반 '뉴스' 티어 {n_excl}건 지수 계산에서 제외"
                  f"(LLM 재검증 전까지 신뢰도 부족 — gkg-verify로 승격 가능)")
        ev = ev[~gkg_news_noise]
    if len(ev) == 0:
        print("[index] 지수 반영 가능한 이벤트 없음(GKG 뉴스 티어 전량 제외됨)"); return pd.DataFrame()

    cfg = IndexConfig(**(C.load_yaml("index.yaml") or {}))
    rel = _reliability_map(); conc_static = _concentration_map()
    conc_df, hhi_df = _load_refdata()
    sign = cfg.direction_sign

    ev = ev.copy()
    ev["date"] = pd.to_datetime(ev["obs_date"], errors="coerce")
    n_drop = int(ev["date"].isna().sum())
    if n_drop:
        print(f"  [warn] 날짜 미상 이벤트 {n_drop}건 지수에서 제외(obs_date/pub_date 없음)")
    ev = ev.dropna(subset=["date"])
    # 미래 날짜 이벤트 방어(실측 2026-07-09): LLM이 전망 시점을 obs_date로 뽑은 잔존분이
    # 미래 주차 지수를 만들어내는 것 방지(extract.py에서 근본 교정, 여기는 최후 방어선).
    n_fut = int((ev["date"] > pd.Timestamp.now()).sum())
    if n_fut:
        print(f"  [index] 미래 obs_date 이벤트 {n_fut}건 지수에서 제외")
        ev = ev[ev["date"] <= pd.Timestamp.now()]
    if len(ev) == 0:
        print("[index] 날짜 있는 이벤트 없음(obs_date/pub_date 확인)"); return pd.DataFrame()

    # 동일 사건 반복보도 중복합산 방지(실측 2026-07-08): 진행형 위기(예: DRC 코발트 수출중단)는
    # Argus 일일보고서 등에서 매일 거의 같은 근거문구로 재보도됨 — 이걸 그대로 합산하면 "같은 위기가
    # 계속 진행 중"이 "매일 새 위기 발생"처럼 과대산정됨. 같은 광종·같은 달(month)·근거인용 앞 40자가
    # 같으면 동일 사건의 반복보도로 간주해 최고 severity 1건만 남김(문서/이벤트 원본은 삭제하지 않음,
    # 지수 산출에서만 dedup). 최초 실측(2026-07-08, 기관보고서 6,510건 소규모 코퍼스): 53건(<1%),
    # CO(코발트)에 집중 — 이 수치는 GKG 병합 전 초기 예시일 뿐, 현재 프로덕션 규모(181만 건)에서는
    # 훨씬 큰 비중을 차지한다. 실측 재확인(2026-07-16, DB 직접 재실행, GEO_EVENT_SOURCE=db 기준):
    # 전체 1,815,193건(날짜있음) 중 이 단계에서 471,107건(약 26%) 제거 → 잔존 1,344,086건.
    # (동일 재실행에서 후속 근사중복 단계가 추가로 112,167건 제거 → 최종 지수계산 대상 1,231,919건.)
    ev["_quote_key"] = ev["evidence_quote"].fillna("").str.strip().str[:40]
    ev["_month"] = ev["date"].dt.to_period("M")
    before = len(ev)
    ev = (ev.sort_values("severity", ascending=False)
            .drop_duplicates(subset=["commodity", "_month", "_quote_key"], keep="first"))
    n_dedup = before - len(ev)
    if n_dedup:
        print(f"  [index] 동일사건 반복보도 중복 {n_dedup}건 제외(월+광종+근거문구 동일, 최고심각도만 유지)")
    # 근사 중복 강화(2026-07-15, 외부감사 B-1④ 1단계): 재보도는 문구가 '미묘하게' 달라
    # 정확일치 키를 빠져나감 — ① 정규화 키(소문자·숫자/구두점/공백 제거 후 앞 80자: 날짜·
    # 수치·표기 변형 흡수) ② 토큰 정렬 키(어순 변형 흡수)로 2차·3차 제거. 임베딩(BGE-M3)
    # 클러스터링은 2단계(GPU 배치 필요) — 표본 검증으로 잔존율을 정량화해 필요성 판단.
    q = ev["evidence_quote"].fillna("").astype(str).str.lower()
    ev["_nkey"] = q.str.replace(r"[\d\W_]+", "", regex=True).str[:80]
    ev["_tkey"] = q.str.replace(r"[^\w가-힣 ]+", " ", regex=True).str.split().map(
        lambda t: " ".join(sorted(t)[:10]) if isinstance(t, list) else "")
    b2 = len(ev)
    ev = ev[~((ev["_nkey"].str.len() >= 20)
              & ev.duplicated(subset=["commodity", "_month", "_nkey"], keep="first"))]
    ev = ev[~((ev["_tkey"].str.len() >= 20)
              & ev.duplicated(subset=["commodity", "_month", "_tkey"], keep="first"))]
    n_near = b2 - len(ev)
    if n_near:
        print(f"  [index] 근사 중복(정규화·토큰 키) {n_near}건 추가 제외")

    ev["yr"] = ev["date"].dt.year
    ev["rel"] = ev["source"].map(rel).fillna(1.0)

    if conc_df is not None:   # USGS refdata 우선(연도별 국가점유 + HHI배수, as-of 조인)
        first_rel = conc_df.groupby("commodity")["release"].min()
        n_leak = int((ev["yr"] < ev["commodity"].map(first_rel)).sum())
        if n_leak:
            print(f"  [index] 시점정합성: {n_leak}건은 해당 광종 최초 USGS 릴리스 이전 이벤트 → "
                  f"최초 릴리스로 폴백(그보다 과거 데이터 없음, 불가피)")
        # 이벤트 단위 row-wise as-of 조인은 프로덕션 규모(수십만~수백만 건)에서 너무 느려
        # (commodity[,country])×연도의 작은 그리드로 미리 계산해 벡터화 merge(2026-07-22).
        years = range(int(ev["yr"].min()), int(ev["yr"].max()) + 1)
        conc_grid = _asof_grid(conc_df, ["commodity", "country"], "weight", years)
        hhi_grid = _asof_grid(hhi_df, ["commodity"], "hhi_mult", years)
        ev = ev.merge(conc_grid, on=["commodity", "country", "yr"], how="left")
        ev["conc"] = ev["weight"].fillna(1.0)
        ev = ev.drop(columns="weight").merge(hhi_grid, on=["commodity", "yr"], how="left")
        ev["hhi_mult"] = ev["hhi_mult"].fillna(1.0)
    else:                     # 폴백: sources.yaml 정적값
        ev["conc"] = (ev["commodity"] + ":" + ev["country"].fillna("")).map(conc_static).fillna(1.0)
        ev["hhi_mult"] = 1.0
    ev["sgn"] = ev["direction"].map(sign).fillna(0.2)
    ev = _apply_kr_exposure(ev)     # 이중 노출: 글로벌 공급충격 × 한국 수입의존(B-1①)
    if score_formula == "sum":
        # B-3(피드백기반_수정플랜 P2) 대안: 곱셈 성분(rel·conc·hhi_mult·imp_mult)을 "중립값
        # 1.0 대비 조정폭"으로 재해석해 severity에 가산 — 한 성분이 극단값이어도 severity
        # 기여분은 보존되어 곱셈식보다 단일성분 오류에 덜 민감.
        ev["score"] = ev["sgn"] * (ev["severity"].astype(float) + (ev["rel"] - 1.0)
                                    + (ev["conc"] - 1.0) + (ev["hhi_mult"] - 1.0)
                                    + (ev["imp_mult"] - 1.0))
    elif score_formula == "loggeo":
        # 기하평균 스타일: 곱셈식(산술곱)은 한 성분이 10배면 점수도 10배지만, 5개 성분의
        # 로그평균 후 지수화하면 10배 성분도 10^(1/5)≈1.58배로 완화됨 — "한 성분 오류에 민감"
        # 문제를 정면으로 겨냥한 대안.
        comps = np.log(np.clip(ev["severity"].astype(float), 1e-3, None) + 1.0), \
            np.log(np.clip(ev["rel"], 1e-3, None)), np.log(np.clip(ev["conc"], 1e-3, None)), \
            np.log(np.clip(ev["hhi_mult"], 1e-3, None)), np.log(np.clip(ev["imp_mult"], 1e-3, None))
        ev["score"] = ev["sgn"] * (np.exp(sum(comps) / 5.0) - 1.0)
    else:
        ev["score"] = (ev["severity"].astype(float) * ev["rel"] * ev["conc"]
                       * ev["hhi_mult"] * ev["sgn"] * ev["imp_mult"])

    # ── 미디어 볼륨 드리프트 정규화(2026-07-15, 외부감사 B-1②) ──
    # 코퍼스 총량이 시간에 따라 변해(실측: 2016년 29.2만/년 → 2020~22년 12.5만/년으로 감소
    # 후 회복 — 증가 일변도라는 통념과 반대) 시간축 눈금이 왜곡됨. 주간 전체(광종 무관)
    # 이벤트량의 장기 기저(EWMA 52주)로 나눠 세속적 변화만 제거한다 — 분모가 '느린' 기저라
    # 주간 급증(실제 위기 신호)은 보존되고, 평균 1 정규화 + 0.5~2.0 클립으로 지수 앵커를
    # 근사 보존하며 초기 저커버 구간의 과대 증폭을 방지한다.
    if volume_norm:
        wk_key = ev["date"].dt.to_period("W").dt.start_time
        vol = wk_key.value_counts().sort_index()
        drift = (vol.ewm(halflife=52).mean() / vol.ewm(halflife=52).mean().mean()).clip(0.5, 2.0)
        ev["score"] = ev["score"] / wk_key.map(drift).fillna(1.0)
        print(f"  [index] 볼륨 드리프트 정규화: 분모 {drift.min():.2f}~{drift.max():.2f} (EWMA 52주·평균1·클립 0.5~2)")
    else:
        print("  [index] 볼륨 드리프트 정규화 건너뜀(volume_norm=False, B-5 검증 전용)")

    # ── 사건 지속성: stock/flow 감쇠 클래스(2026-07-15, 외부감사 B-1③) ──
    # 수출통제(효력 지속)와 파업(단기 종료)이 같은 주에만 계상되던 것을, 사건유형별 반감기의
    # 정규화 기하 커널(질량 1 — 총량 보존)로 후속 주간에 분산한다. event_type이 영/한/대소문자
    # 혼재(정책/policy/Geopolitical...)라 패턴 매칭으로 분류.
    et = ev["event_type"].fillna("").astype(str).str.lower()
    is_stock = et.str.contains("policy|정책|제재|sanction|export|규제|geopolit", regex=True)
    is_flow = et.str.contains("뉴스|news|파업|strike|재해|disaster|사고|accident|분쟁|conflict|시위|protest",
                              regex=True)
    ev["_decay"] = np.where(is_stock, "stock", np.where(is_flow & ~is_stock, "flow", "mid"))

    out = []
    # Y(연간): 연간 발행 보고서(USGS·IEA·광업요람 등)의 이벤트가 자연스럽게 연 단위 배경
    # 신호로 집계됨(2026-07-12, "연간 발행물은 연 단위 적용" 방침). 붙임1 다중 주기 요구 대응.
    # scale_k는 "주간 P90=지수 88" 앵커(주간 기준) — 월/연은 raw가 기간 길이만큼 커지므로
    # 동일 앵커 의미를 유지하려면 주기 배수를 곱한다(정상 주간율 가정 하 P90-상당 기간=88).
    _FREQ_MULT = {"W": 1.0, "M": 52.0 / 12.0, "Y": 52.0}
    # 감쇠 반감기(주): stock=수출통제·제재·정책(1분기), flow=보도·파업·재해(단기), mid=기타.
    _HL = {"stock": 13, "flow": 2, "mid": 4}
    grid_end = ev["date"].max()

    def _decayed_weekly(sub: pd.DataFrame) -> tuple:
        """이벤트 → 주간 그리드 점수(클래스별 커널 전방 분산 합) + 실이벤트 수."""
        grid = pd.date_range(sub["date"].min(), grid_end, freq="W")
        total = np.zeros(len(grid))
        for cls, hl in _HL.items():
            s = (sub[sub["_decay"] == cls].set_index("date")["score"]
                 .resample("W").sum().reindex(grid, fill_value=0.0))
            a = 0.5 ** (1.0 / hl)
            w = (1 - a) * a ** np.arange(4 * hl + 1)
            w = w / w.sum()                    # 질량 1 — 총량 보존(앵커 근사 유지)
            total += np.convolve(s.values, w)[: len(grid)]
        cnt = sub.set_index("date").resample("W").size().reindex(grid, fill_value=0)
        return pd.Series(total, index=grid), cnt

    for c, sub in ev.groupby("commodity"):
        wk_score, wk_cnt = _decayed_weekly(sub)
        for freq, flabel in (("W", "W"), ("MS", "M"), ("YS", "Y")):
            if flabel == "W":
                raw, cnt = wk_score, wk_cnt
            else:                              # 감쇠 반영된 주간 시계열을 상위 주기로 합산
                raw, cnt = wk_score.resample(freq).sum(), wk_cnt.resample(freq).sum()
            g = pd.DataFrame({"period": raw.index, "raw_score": raw.values,
                              "n_events": cnt.reindex(raw.index).fillna(0).astype(int).values})
            # 실이벤트가 없어도 감쇠 잔존 신호가 있으면 발행(지속성 반영이 목적) —
            # 둘 다 없는 공백 기간만 미발행.
            g = g[(g["n_events"] > 0) | (g["raw_score"] > 1e-9)]
            g["commodity"] = c
            g["freq"] = flabel
            k = float((cfg.scale_k_by_commodity or {}).get(c, cfg.scale_k)) * _FREQ_MULT[flabel]
            g["index"] = _normalize(g["raw_score"], cfg.normalize, k)
            out.append(g)
    res = pd.concat(out, ignore_index=True)
    res["period"] = pd.to_datetime(res["period"]).dt.strftime("%Y-%m-%d")
    return res[["commodity", "freq", "period", "raw_score", "n_events", "index"]]


def run():
    C.ensure_dirs()
    res = compute()
    if len(res):
        store.write_index(res)
        from .wiki import generate
        generate(res)
        print(f"[index] {len(res)}행 산출 → {C.INDEX}")
        print(res[res.freq=="M"].groupby("commodity")["n_events"].sum().to_string())
    return res


if __name__ == "__main__":
    run()
