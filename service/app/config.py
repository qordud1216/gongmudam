"""설정 파일(config.json) 읽기·쓰기. 없으면 config.example.json 을 복사해 만든다."""
from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
from .runtime_paths import state_root, no_llm

CONFIG_PATH = state_root() / "config.json"
EXAMPLE_PATH = ROOT / "config.example.json"
_lock = threading.RLock()


def load() -> dict[str, Any]:
    with _lock:
        if not CONFIG_PATH.exists():
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(EXAMPLE_PATH, CONFIG_PATH)
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if no_llm():
            value['llm'] = {'active': 'offline', 'profiles': {'offline': {'provider': 'offline'}}}
        return value


def save(cfg: dict[str, Any]) -> None:
    with _lock:
        if no_llm() and cfg.get('llm') != load()['llm']:
            raise ValueError('이 실행본은 LLM을 사용하지 않습니다. 모델·키 설정은 변경할 수 없습니다.')
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def update(change):
    """Serialize read/modify/write against in-process configuration readers."""
    with _lock:
        cfg = load()
        result = change(cfg)
        save(cfg)
        return result


def active_profile(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load()
    llm = cfg.get("llm", {})
    name = llm.get("active", "offline")
    prof = dict(llm.get("profiles", {}).get(name) or {"provider": "offline"})
    prof["_name"] = name
    return prof


def public_llm_view(cfg: dict[str, Any]) -> dict[str, Any]:
    """화면에 보여줄 LLM 설정 (키 값은 가린다)."""
    llm = cfg.get("llm", {})
    profiles = {}
    for name, p in llm.get("profiles", {}).items():
        q = {k: v for k, v in p.items() if k != "api_key"}
        q["has_api_key"] = bool(p.get("api_key"))
        profiles[name] = q
    return {"active": llm.get("active", "offline"), "profiles": profiles}
