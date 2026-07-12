# komir 수집기 (collector/)

분석기(geo)와 **다른 서버**에서 단독 실행되는 수집 전용 도커. geo 코드에 의존하지 않으며,
분석기와의 접점은 **출력 파일 계약**뿐이다.

## 수집 대상
| 모듈 | 소스 | 산출 |
|---|---|---|
| gkg | GDELT GKG 2.1 증분(15분 주기, 타임스탬프 직접 생성 — 마스터리스트 불필요) | `$COLLECT_OUT/gkg/YYYY/*.gkg.csv.zip` |
| gnews | Google News RSS(광종별 공급망 쿼리) | `$COLLECT_OUT/inbox/gnews/*.txt` |
| gdelt | GDELT DOC API(기사목록) | `$COLLECT_OUT/inbox/gdelt/*.txt` |
| us_trade | **미국 공시** — Federal Register 공식 API(BIS 수출통제·Entity List / USTR 관세·301조 / ITA 반덤핑) | `$COLLECT_OUT/inbox/us_trade/*.txt` |
| cn_trade | **중국 공시** — 상무부 안전관제국(aqygzj.mofcom.gov.cn: 수출통제 공고·실체명단·대변인 문답) | `$COLLECT_OUT/inbox/cn_trade/*.txt` |

## 실행
```bash
docker compose up -d --build          # 데몬(기본 60분 주기)
docker compose run --rm collector python -m collector run --only us_trade,cn_trade   # 1회
```

## 분석 서버와의 연결 (파일 계약)
수집기는 공유 NAS에 쓰고, 분석 서버는 같은 경로를 읽는다:
```bash
# 분석 서버에서 —
rsync -a $NAS/collect_out/inbox/  $GEO_DATA/inbox/          # 또는 GEO_DATA inbox를 NAS로 지정
python -m geo ingest && python -m geo extract && python -m geo index
python -m geo gkg-parse --bulk-root $NAS/collect_out/gkg    # GKG 증분 파싱(재개형 — 새 파일만 처리)
```
- inbox 텍스트 형식·GKG zip 형식은 분석기의 기존 입력 형식과 동일(코드 공유 없이 형식만 계약).
- 상태/중복방지: `$COLLECT_OUT/_state/` (seen 해시·gkg 마지막 타임스탬프) — 볼륨에 있으므로
  컨테이너 재생성에도 유지.

## 참고
- cn_trade: 메인 mofcom.gov.cn은 JS 렌더링이라 부적합 — 수출통제 주관국(안전관제국) 사이트가
  순수 HTML이며 내용도 정확히 표적(战略矿产 两用物项 수출통제 공고 등). 간헐 접속차단 시 다음
  주기에 자연 재시도.
- us_trade: Federal Register는 관보(법적 공시 원본) — 보도자료보다 확정력 높음. 키 불필요.
- 역사 백필: gkg 벌크는 `geo/collectors/gkg_bulk_download.py`(분석 리포에 유지), us_trade는
  `python -m collector run --only us_trade` 최초 실행 시 2016-01-01부터 자동 백필.
