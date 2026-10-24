"""Configure an OpenAI-compatible model for a submission package."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]


def normalize_base_url(value: str) -> str:
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("base URL은 http 또는 https 주소여야 합니다.")
    if not parts.hostname:
        raise ValueError("base URL에 호스트가 필요합니다.")
    if parts.username is not None or parts.password is not None:
        raise ValueError("base URL에 사용자 정보(credentials)를 넣을 수 없습니다.")
    if parts.query or parts.fragment:
        raise ValueError("base URL에 query 또는 fragment를 넣을 수 없습니다.")
    # Accessing port also validates malformed port values.
    try:
        parts.port
    except ValueError as exc:
        raise ValueError("base URL의 포트가 올바르지 않습니다.") from exc
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc, path, "", ""))


def configure(root: Path, profile: str, base_url: str, model: str,
              api_key_env: str = "", json_object: bool = False) -> dict:
    root = Path(root)
    path = root / "config.json"
    source = path if path.exists() else root / "config.example.json"
    cfg = json.loads(source.read_text(encoding="utf-8"))
    llm = cfg.setdefault("llm", {})
    profiles = llm.setdefault("profiles", {})
    entry = {
        "provider": "openai_compatible",
        "base_url": normalize_base_url(base_url),
        "model": model,
        "temperature": 0,
        "max_tokens": 700,
        "timeout": 180,
    }
    if api_key_env:
        entry["api_key_env"] = api_key_env
    if json_object:
        entry["extra_body"] = {"response_format": {"type": "json_object"}}
    profiles[profile] = entry
    llm["active"] = profile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="config.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(cfg, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="submission_model")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="")
    parser.add_argument("--json-object", action="store_true")
    args = parser.parse_args()
    try:
        configure(ROOT, args.profile, args.base_url, args.model,
                  args.api_key_env, args.json_object)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Configured model profile '{args.profile}'. API key values are read only from the named environment variable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
