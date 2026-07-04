# -*- coding: utf-8 -*-
"""경로·설정 로드. 상태는 전부 GEO_DATA(볼륨) 아래. LLM은 env > yaml 우선."""
import os
from pathlib import Path
try:
    import yaml
except ImportError:
    yaml = None

GEO_DATA = Path(os.environ.get("GEO_DATA", "./geo_data")).resolve()
INBOX = GEO_DATA / "inbox"
ARCHIVE = GEO_DATA / "archive"
FAILED = GEO_DATA / "_failed"
UNCLASSIFIED = GEO_DATA / "_unclassified"
DUPLICATES = GEO_DATA / "_duplicates"
STORE = GEO_DATA / "store"
WIKI = GEO_DATA / "wiki"
CONFIG = GEO_DATA / "config"

MANIFEST = STORE / "manifest.parquet"
EVENTS = STORE / "geo_events.parquet"
INDEX = STORE / "geo_index.parquet"
EXTRACT_LOG = STORE / "extract_log.parquet"   # 추출 시도 이력(0건 문서 재추출 방지)

# 패키지 기본 config (볼륨에 없으면 이걸 사용)
PKG_CONFIG = Path(__file__).resolve().parent / "config"


def ensure_dirs():
    for p in (INBOX, ARCHIVE, FAILED, UNCLASSIFIED, DUPLICATES, STORE, WIKI, CONFIG):
        p.mkdir(parents=True, exist_ok=True)


def load_yaml(name: str) -> dict:
    """CONFIG(볼륨) 우선, 없으면 패키지 기본."""
    for base in (CONFIG, PKG_CONFIG):
        f = base / name
        if f.exists() and yaml is not None:
            return yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    return {}


def llm_config() -> dict:
    """models.yaml + env override. env가 우선."""
    cfg = (load_yaml("models.yaml") or {}).get("extractor", {})
    envmap = {
        "provider": "LLM_PROVIDER", "base_url": "LLM_BASE_URL", "model": "LLM_MODEL",
        "api_key_env": "LLM_API_KEY_ENV", "temperature": "LLM_TEMPERATURE",
        "concurrency": "LLM_CONCURRENCY", "batch": "LLM_BATCH",
    }
    for k, env in envmap.items():
        if os.environ.get(env):
            cfg[k] = os.environ[env]
    # 직접 키
    cfg.setdefault("provider", os.environ.get("LLM_PROVIDER", "rule"))
    key_env = cfg.get("api_key_env", "LLM_API_KEY")
    cfg["api_key"] = os.environ.get("LLM_API_KEY") or os.environ.get(key_env, "")
    return cfg
