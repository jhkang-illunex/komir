# -*- coding: utf-8 -*-
"""서빙 레이어 공통 LLM 클라이언트.

geo/llm/openai_compat.py(provider 무관 어댑터, rag/ragkit/generate.py가 이미
재사용 중, .env의 LLM_PROVIDER/LLM_BASE_URL/LLM_MODEL/LLM_API_KEY/LLM_TEMPERATURE
규약)를 그대로 재노출한다 — 신규 LLM 클라이언트 재구현 금지.

2026-08-11 연계 현황 정리(병합계획_komis-report-generator_260811.md 관련 작업
중 사용자 질문에 대한 답): 이식 전에는 LLM/임베딩 설정이 서로 안 이어져 있었다.
- **LLM(채팅)**: komir는 이 파일이 감싸는 OpenAICompatChat(requests 기반, 커넥션
  풀 재사용 등 실측 튜닝 반영) 하나만 써왔다(geo 추출·rag/ragkit/generate.py).
  외부 repo(komis-report-generator-main)의 search/llm.py는 env 변수 이름은
  우연히 같지만(LLM_BASE_URL 등) httpx 기반의 **별개 클라이언트**
  (OpenAICompatibleJsonLLM)를 갖고 있었다 — 그대로 들여오면 프로젝트에 LLM
  호출 클라이언트가 2벌 생긴다. 이 파일의 `KomirJsonLLM`이 그 문제를 없앤다:
  구조화 출력(JSON Schema 강제+1회 복구 재시도) 로직은 값어치가 있어 이식하되,
  실제 HTTP 호출은 komir의 OpenAICompatChat.complete()에 위임한다 — 클라이언트는
  하나만 남는다.
- **임베딩**: 전혀 안 이어져 있었다(지금도 그대로). komir 쪽 실제 구현
  (`rag/ragkit/embed.py`)은 `.env`의 EMBEDDING_BASE_URL을 참조조차 하지 않고
  sentence-transformers(intfloat/multilingual-e5-small)를 코드에 하드코딩해
  프로세스 내부에서 직접 로드한다(HTTP 서버 없음). 외부 repo의
  vector_index/embeddings.py는 반대로 OpenAI 호환 HTTP `/embeddings` 엔드포인트
  호출을 전제(`KOMIS_EMBEDDING_*`라는 별도 이름 체계)한다 — 아키텍처 가정 자체가
  다르다. rag_chat 이식(services/rag_chat/app/retrieval/unstructured.py)에서는
  komir의 로컬 직접로드 방식을 그대로 쓰고 벡터 저장소만 Qdrant로 바꾼다(§4·§5-4
  설계 그대로) — HTTP 임베딩 클라이언트는 채택하지 않는다.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

_logger = logging.getLogger(__name__)

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from geo.llm.openai_compat import OpenAICompatChat  # noqa: E402

from .config import get_settings

OutputT = TypeVar("OutputT", bound=BaseModel)

_FENCED_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", flags=re.DOTALL | re.IGNORECASE)


class LLMError(RuntimeError):
    """모델 전송·응답 실패의 공통 베이스."""

    def __init__(self, message: str, *, record: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.record = record


class LLMOutputError(LLMError):
    """모델이 유효한 구조화 응답을 끝내 만들지 못했을 때."""


#: `KomirJsonLLM.invoke()` 호출부가 "LLM 호출 실패 시 부분 결과라도 살린다"는
#: 부분열화 계약을 지키려면 `except LLMError`만으로는 부족하다 — 실제 HTTP는
#: `geo/llm/openai_compat.py`의 `OpenAICompatChat.complete()`가 수행하는데,
#: 재시도 소진 후 HTTP 429/5xx는 평범한 `RuntimeError`로, 타임아웃·커넥션
#: 오류는 `requests.RequestException`(OSError의 서브클래스)으로 던진다 — 둘 다
#: `LLMError`의 서브클래스가 아니다(정의가 서로 다른 파일에 독립적으로 있음).
#: 2026-08-13 herd 코드리뷰에서 `pageindex_agent.agentic_lookup()`이 딱 이
#: 간극 때문에 이미 모은 근거를 유실하는 걸 실측으로 발견했다 — 그 수정을
#: 여기로 승격해 LLM 호출부 전체(route/reformulate/verify/pageindex_agent)가
#: 공유한다. `requests`를 이 파일이 직접 import 안 해도 되게, 그 부모 클래스인
#: OSError로 넓게 잡는다(HTTP 클라이언트 구현 세부사항에 결합되지 않기 위함).
LLM_TRANSIENT_ERRORS = (LLMError, RuntimeError, OSError)


@dataclass(frozen=True, slots=True)
class LLMInvocation:
    """검증된 모델 출력과 감사용 호출 기록."""

    output: Any
    record: dict[str, Any]


def parse_json_object(content: str) -> dict[str, Any]:
    """평문/펜스/주변텍스트가 섞인 응답에서 JSON 객체를 뽑아낸다."""

    text = content.strip()
    fenced = _FENCED_RE.fullmatch(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model output must be a JSON object")
    return value


def get_chat_client(cfg: dict | None = None) -> OpenAICompatChat:
    """평문 응답용 komir 표준 LLM 클라이언트(단일 호출, 재시도·커넥션풀 내장)."""

    return OpenAICompatChat(cfg or get_settings().llm_cfg())


class KomirJsonLLM:
    """구조화(JSON Schema) 출력이 필요한 호출용 — OpenAICompatChat 위의 얇은 층.

    search/graph.py 등이 기대하는 invoke(task=, instructions=, payload=,
    output_model=, max_tokens=) -> LLMInvocation 계약을 만족한다(외부 repo의
    JsonLLM Protocol과 동일 시그니처로 맞춤 — 이식된 그래프 코드를 고치지 않아도
    되게). 실제 HTTP는 OpenAICompatChat.complete()가 수행 — 클라이언트를
    새로 만들지 않는다."""

    def __init__(self, cfg: dict | None = None) -> None:
        self._chat = get_chat_client(cfg)
        self._json_mode = True

    def invoke(
        self,
        *,
        task: str,
        instructions: str,
        payload: Mapping[str, Any],
        output_model: type[OutputT],
        max_tokens: int,
    ) -> LLMInvocation:
        """작업 하나를 호출하고, 무효 출력이면 1회 복구를 시도한다."""

        schema = output_model.model_json_schema()
        system_prompt = (
            f"{instructions}\n\n"
            "반환할 JSON은 다음 JSON Schema를 만족해야 한다.\n"
            f"{json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}"
        )
        user_content = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))

        previous_content = ""
        previous_error = ""
        call_record: dict[str, Any] = {
            "task": task,
            "instructions": instructions,
            "input": dict(payload),
            "output_schema": output_model.__name__,
            "max_tokens": max_tokens,
            "attempts": [],
        }
        for attempt in range(2):
            if attempt:
                user_content = json.dumps(
                    {
                        "task": "repair_output",
                        "original_input": dict(payload),
                        "previous_output": previous_content[:2000],
                        "error": previous_error[:500],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            attempt_record: dict[str, Any] = {"attempt": attempt + 1}
            try:
                result = self._chat.complete(system_prompt, user_content, max_tokens=max_tokens)
                raw_content = result.text
                attempt_record["raw_content"] = raw_content
                previous_content = raw_content
                parsed = parse_json_object(previous_content)
                validated = output_model.model_validate(parsed)
                attempt_record["parsed_output"] = validated.model_dump(mode="json")
                call_record["attempts"].append(attempt_record)
                call_record["outcome"] = "success"
                return LLMInvocation(output=validated, record=call_record)
            except (json.JSONDecodeError, ValueError, ValidationError) as exc:
                previous_error = f"{type(exc).__name__}: {exc}"
                attempt_record.setdefault("raw_content", previous_content)
                attempt_record["error"] = previous_error
                call_record["attempts"].append(attempt_record)
                # "LLM 경과" 로깅(사용자 요청, 2026-08-28) — 이 복구 재시도는
                # 지금까지 call_record에만 남고 로거로는 안 나갔다. 모든
                # KomirJsonLLM 호출자(route/reformulate/verify·intent·
                # page_recommend·_classify_abstain 등)가 공유하는 지점이라
                # 여기 한 곳에서만 로깅해도 전부 커버된다.
                _logger.warning(
                    "%s: 1차 출력 검증 실패, 복구 재시도(%s)", task, previous_error
                )
                continue
        call_record["outcome"] = "invalid_output"
        _logger.error(
            "%s: 복구 재시도 후에도 유효한 JSON 출력 실패(%s) — 호출부 폴백으로 처리됨",
            task, previous_error,
        )
        raise LLMOutputError(
            f"{task} returned invalid JSON after one repair attempt: {previous_error}",
            record=call_record,
        )
