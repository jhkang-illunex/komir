# -*- coding: utf-8 -*-
"""dense 임베딩. intfloat/multilingual-e5-small — 한국어 포함 다국어 지원, 로컬 실행
(임베딩용으로는 LLM 서버가 필요 없음 — geo 파이프라인의 vLLM/LLM_BASE_URL과 별개).
e5 계열은 "query: "/"passage: " 접두어를 붙여야 정확도가 나온다(모델 카드 규약)."""
from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "intfloat/multilingual-e5-small"
DIM = 384

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def encode_passages(texts: list[str], batch_size: int = 64) -> np.ndarray:
    model = get_model()
    prefixed = [f"passage: {t}" for t in texts]
    return model.encode(prefixed, batch_size=batch_size, normalize_embeddings=True,
                         show_progress_bar=len(texts) > 200)


def encode_query(text: str) -> np.ndarray:
    model = get_model()
    return model.encode([f"query: {text}"], normalize_embeddings=True)[0]


if __name__ == "__main__":
    v = encode_query("진단모델 AUC는 얼마인가?")
    print("dim:", len(v), "norm:", float((v ** 2).sum() ** 0.5))
