# 최종 DB화 · 원본→테이블 맵핑 · 변환 내용 정리

> 핵심광물 위기진단·수입예측 프로젝트 데이터 기반(`claude_output/db/minerals.duckdb`)
> 작성일: 2026-06-30

---

## 1. 최종 DB 현황 (DuckDB, 16 테이블 + 1 뷰, 원본 1,092건)

### 차원(Dimension)
| 테이블 | 행수 | 내용 |
|---|---|---|
| `dim_commodity` | 5 | 5대 핵심광물(CU/NI/LI/CO/REE) |
| `dim_commodity_map` | 18 | 원천 표기명→표준코드 |
| `dim_hs_commodity` | 542 | HS10→광종 권위 매핑(검증완료) |
| `dim_series` | 15 | 거시·지수·환율 시계열 메타 |

### 사실(Fact) — 정량
| 테이블 | 행수 | 내용 |
|---|---|---|
| `fact_trade` | 105,194 | 관세청 수출입(연·국가·HS, 2013~25) |
| `fact_price` | 62,308 | LME Cash/3M·기준가·연월평균 |
| `fact_indicator` | 11,088 | KOMIS 수급동향/시장동향 지표(월) |
| `fact_series` | 6,569 | BDI·원자재지수·환율·美금융·中수요 |
| `fact_inventory` | 6,090 | LME 재고(주) |
| `fact_production_reserve` | 2,256 | USGS 생산·매장(연·국가) |

### 사실(Fact) — 비정형(지정학)
| 테이블 | 행수 | 내용 |
|---|---|---|
| `doc_raw` | 1,092 | 보고서 원본(PPS 877·KOMIS 186·AsianMetal 18·Argus 8·IEA 3) |
| `geo_event` | 1,742 | 추출 이벤트(baseline 1,717 + **llm 25**) |
| `fact_geopolitical_weekly` (뷰) | 27 | 광종×주 지정학 인덱스(llm 기준) |

### 모델 입력(Mart)
| 테이블 | 행수 | 내용 |
|---|---|---|
| `mart_weekly_diagnosis` | 3,805 | **[진단]** 주간 6변수+신규+교사신호+지정학⑥ |
| `mart_annual_forecast` | 65 | **[예측]** 연간 수입(+1년후 타깃) |
| `agg_trade_annual` | 65 | 광종·연 교역집계(HHI/YoY/CAGR) |
| `agg_production_annual` | 10 | 광종·연 생산 HHI |

---

## 2. 원본 데이터 → 테이블 맵핑

| 원본 파일/폴더 | 형식 | → 테이블 | 변환·처리 |
|---|---|---|---|
| `0.KOMIS 공급망통계` (주간 평균) | xlsx | `fact_price`(Cash/3M) | 멀티헤더 파싱→long |
| `1.주간가격및재고량_{광종}` | xlsx | `fact_price`(REF)·`fact_inventory` | 전치표 파싱 |
| `2~5.*.csv`(BDI·원자재·환율·美금융·中) | csv(CP949) | `fact_series` | 인코딩·날짜 정규화 |
| `관세청 수출입DB 2013~25` | xlsx(43MB) | `fact_trade` | openpyxl 스트리밍 적재 |
| `HS코드분류__최종` | xlsx | `dim_hs_commodity` | 종합분류→HS10 매핑(검증) |
| `USGS_엑셀정리본_2026` | xlsx | `fact_production_reserve` | 피벗→long, 점유율컬럼 제외 |
| `KOMIS 수급동향/시장동향/광물종합` | xlsx | `fact_indicator` | wide(월)→long |
| **`보고서_2` Asian Metal 리튬 주간** | PDF×18 | `doc_raw`→`geo_event` | 2단컬럼 추출→이벤트 |
| **`보고서_2` Argus 비철 일간** | PDF×8 | `doc_raw`→`geo_event` | 2단컬럼 추출→이벤트 |
| **`보고서_1` IEA Critical Minerals** | PDF×3 | `doc_raw`→`geo_event` | 타깃 단락 추출 |
| **`보고서_1` 전략광종월간·자원정보포커스** | PDF×163 | `doc_raw`→`geo_event` | 단단 추출+한국어 키워드 |
| **`보고서_1` 자원정보포커스·전략광종(HWP)** | HWP×23 | `doc_raw`→`geo_event` | **HWP 직접파서(OLE+zlib+HWPTAG)** |
| **`조달청보고서`(비철금속 동향·전망)** | PDF×877 | `doc_raw`→`geo_event` | 전량 카탈로그, 최근 66건 분석(동·니켈 신호) |
| `보고서_1` GSCPI(공급망압력지수) | xls | (적재대상) | 정량지표, 추가적재 가능 |

> 적재상태: 전체 1,092건 중 **125건 분석완료(analyzed)**, 967건 카탈로그(hold) — 과거분은 동일 명령으로 배치 분석 가능
> 미적재/보류: 광물종합지수(구조상이), 우드맥킨지 zip(분기). KOMIS 주간광물동향 HWP 538건

---

## 3. 변환·처리 내용 요약

### 정량 데이터 (canonical 적재)
- 7개 원천을 **long/tidy 단일 스키마**로 통일(광종·날짜·단위·출처)
- 관세청 HS코드 → 광종 **권위 매핑 검증**: 5대 광종 미매핑 0건, 충돌 0건(창연=비스무스 동의어뿐)
- 적재 멱등화(소스별 삭제후삽입) + DataFrame 일괄삽입으로 고속화

### 비정형 데이터 (지정학 파이프라인)
- **doc_raw(원본)/geo_event(분석) 2단 분리**, status 기반 수집→분석 파이프라인
- PDF 추출: 2단컬럼(Argus·AsianMetal) / 단단(KOMIS) 자동분기
- 추출기 2종: 규칙기반(baseline) + **LLM(운영, Anthropic 어댑터)**
- **5대 광종 전체 지정학 커버리지 확보**(동·니켈은 KOMIS 한국어 본문에서 확보)

### 변환 결과
| 대상 | 결과 |
|---|---|
| PDF 보고서(1,069건: 일반 192 + 조달청 877) | ✅ doc_raw 전량 적재 |
| **KOMIS HWP 23건** | ✅ **HWP 직접파서로 적재 완료** (한컴·MCP 불필요) |
| **조달청 887건** | ✅ 전량 카탈로그, 최근 66건 분석(구리 지정학 신호 확보) |

> **HWP 해결**: 한컴 한글 미설치로 `hwp_export_pdf`(COM 구동) 불가했으나, **HWP5 바이너리(OLE+zlib+HWPTAG_PARA_TEXT)를 순수 파이썬으로 직접 파싱**(`hwp_extract.py`)하여 텍스트 추출 → 파이프라인 적재. 칠레 Escondida 동광 파업, 러시아 제재 Norilsk 니켈 공급차질, 미·중 관세전쟁 등 **역사적(2015~18) 지정학 이벤트까지 확보**. 동일 파서로 주간 538건도 추가 가능.

---

## 4. 모델 준비 상태

| 모델 | 입력 테이블 | 상태 |
|---|---|---|
| **수급위기 진단** | `mart_weekly_diagnosis` | 변수 ①②③⑤+교사신호+⑥(CO·CU·LI·NI) 준비. ④(소비)·REE가격 갭 |
| **수입 예측** | `mart_annual_forecast` | 연간 패널 가능. **월간 수입통계 확보 시 월간 전환** |

> 결론: 정량 7종 + 비정형 지정학까지 단일 DuckDB로 통합 완료. 진단모델은 프로토타입 학습 가능 단계, 예측모델은 연간 단위 가능(월간은 데이터 확보 후).
