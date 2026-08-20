# -*- coding: utf-8 -*-
"""응답 경계 직렬화 — pandas/numpy 스칼라를 JSON 안전 타입으로 정규화.

model_loaders.py가 돌려주는 DataFrame/dict는 numpy.int64·numpy.bool_·
pandas.Timestamp 등을 그대로 담고 있다(FastAPI의 기본 jsonable_encoder가
numpy 스칼라를 자동 변환하지 않는다 — numpy.int64/bool_는 파이썬 int/bool의
서브클래스가 아니라서 500 오류로 이어질 수 있음). 라우터가 dict를 만드는
시점에 이 모듈을 거쳐 한 번에 정리한다."""
from __future__ import annotations

import datetime
import math

import numpy as np
import pandas as pd


def json_safe(obj):
    if obj is None or obj is pd.NaT:
        return None
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if math.isnan(v) else v
    if isinstance(obj, (pd.Timestamp, datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, np.datetime64):
        return pd.Timestamp(obj).isoformat()
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, np.ndarray, pd.Series)):
        return [json_safe(v) for v in obj]
    return obj


def df_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame → JSON 안전 dict 리스트(컬럼 순서 유지)."""

    return [json_safe(row) for row in df.to_dict("records")]
