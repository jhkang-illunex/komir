# PageIndex(vendored) — 출처·라이선스·airgap 하드닝 기록

## 출처
- 원본: https://github.com/VectifyAI/PageIndex (MIT License, 동봉 `LICENSE` 참고)
- vendored 커밋: `b723c9f0a70bcf6b1dc16985063fa3b89f2d2441` (2026-08-10)
- vendored 일시: 2026-08-11
- `pageindex_lib/`는 원본 저장소의 `pageindex/` 패키지를 그대로 복사한 것 —
  **`client.py`(`PageIndexClient`, `https://api.pageindex.ai` 유료 클라우드 REST
  클라이언트)만 의도적으로 제거**했다(`__init__.py`에서 해당 import도 함께 제거).

## 왜 pip 패키지(`pip install pageindex`)를 안 쓰고 vendoring했는가
PyPI에 올라온 `pageindex` 패키지(0.2.8)는 이 저장소의 로컬 트리생성 코드가 아니라
`PageIndexClient`(`https://api.pageindex.ai`에 PDF 파일을 업로드하는 REST
클라이언트) **하나만** 노출한다(2026-08-11 실제로 pip install해서 소스 확인).
이 프로젝트는 전 구간 airgap이라 사용 불가 — GitHub 저장소를 직접 clone해
"Self-host" 방식(README의 표현)으로 로컬 실행 가능한 `pageindex/` 패키지 자체를
가져왔다.

## airgap 안전성 실측 검증(2026-08-11)
`pageindex_lib`는 md 기반 트리 생성 시 다음 두 지점에서 외부 네트워크를 탈 수 있다:
1. **litellm의 원격 모델가격표 fetch** — `utils.py`가 토큰 카운팅에 `litellm.
   token_counter()`를 쓰는데, litellm은 import 시(또는 최초 사용 시) 기본적으로
   `https://raw.githubusercontent.com/BerriAI/litellm/...`에서 모델 가격표를
   받아온다(litellm 자체 소스 주석·문서로 확인). `LITELLM_LOCAL_MODEL_COST_MAP=True`
   환경변수로 끄면 litellm 패키지에 내장된 로컬 백업 JSON만 쓴다.
2. **OpenAI SDK의 기본 엔드포인트** — `utils.py`가 `openai.OpenAI()`/
   `openai.AsyncOpenAI()`를 base_url 지정 없이 생성한다. openai-python SDK
   관례상 `OPENAI_BASE_URL` 환경변수가 있으면 그걸 우선 사용한다.

**실측**: `OPENAI_BASE_URL=http://localhost:52302/v1`(komir 로컬 vLLM) +
`LITELLM_LOCAL_MODEL_COST_MAP=True` 설정 후, 실제 문서(`documents/산출물`의 md
1건)로 `--if-add-node-summary yes`(LLM 노드요약 강제 — 실제 LLM 호출 경로를 타는
가장 무거운 옵션)까지 켜서 end-to-end 실행하며, 그 프로세스가 맺은 모든 TCP
연결을 `ss -tnp`로 PID 단위 추적했다. 결과: **`127.0.0.1:52302`(로컬 vLLM) 외
연결 0건.** 실행도 정상 완료(요약 포함된 트리 JSON 정상 생성).

`flash/`(PDF 레이아웃 분석 전용 서브패키지, LLM 없이 순수 로컬 연산)도
`requests`/`urllib`/`httpx`/`http(s)://` 하드코딩 리터럴이 코드에 전혀 없음을
grep으로 확인.

## 사용 규칙(중요)
- **이 vendored 코드를 직접 import하지 말고 반드시 `services/shared/
  pageindex_client.py`(komir 래퍼)를 통해서만 쓸 것** — 그 래퍼가 위 두 환경변수를
  komir 설정(`services/shared/config.py`)에서 강제로 세팅한 뒤에만
  `pageindex_lib`를 import한다. 래퍼를 건너뛰고 `pageindex_lib`를 직접 import하면
  환경변수가 안 걸린 상태로 실행돼 위 두 network 지점이 다시 열릴 수 있다.
- 원본 저장소를 업데이트해서 재-vendoring할 경우, 이 README의 "airgap 안전성
  실측 검증" 섹션을 반드시 재실행하고 커밋 해시·날짜를 갱신할 것 — 신뢰는
  코드 스냅샷 단위이지 "원 저장소가 안전하다"는 일반론이 아니다.
