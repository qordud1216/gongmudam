"""LLM 연결부 (모델 비종속 어댑터).

config.json 의 "llm" 항목에서 프로필을 고르면 연결 대상이 바뀐다.
- provider "offline": LLM 없이 규칙 기반으로만 동작 (키 불필요, 데모·폐쇄망용)
- provider "openai_compatible": /v1/chat/completions 규격을 따르는 모든 서버
  (vLLM, Ollama, LM Studio, llama.cpp server, OpenAI 등)

새 제공자를 붙이려면 BaseProvider 를 상속해 chat() 만 구현하고 PROVIDERS 에 등록한다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import httpx


log = logging.getLogger(__name__)
_capture = ContextVar('local_model_capture', default=None)
_no_inference = ContextVar('no_inference', default=False)


def disabled():
    from .runtime_paths import no_llm
    return no_llm() or _no_inference.get()


@contextmanager
def inference_policy(no_inference=False):
    token = _no_inference.set(no_inference or _no_inference.get())
    try:
        yield
    finally:
        _no_inference.reset(token)


def request_headers(profile: dict[str, Any]) -> dict[str, str]:
    """Use the same credentials for discovery and inference; never expose them in status."""
    key = profile.get("api_key") or ""
    env = profile.get("api_key_env")
    if env and os.environ.get(env):
        key = os.environ[env]
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


@contextmanager
def capture_calls():
    """요청 범위의 선택적 검증 기록. 헤더·API 키는 기록하지 않는다."""
    records=[];token=_capture.set(records)
    try: yield records
    finally: _capture.reset(token)


class LLMError(RuntimeError):
    """모델 호출 실패. str(e) 는 화면에 내도 되는 고정 문구(오류 종류)만 담는다.
    모델·서버가 보낸 본문은 detail 에만 두고 로그로만 남긴다(화면에 내지 않는다)."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(kind)
        self.kind = kind
        self.detail = detail
        if detail:
            log.warning("LLM 오류(%s): %s", kind, detail)


class BaseProvider:
    name = "base"

    def __init__(self, profile: dict[str, Any]):
        self.profile = profile

    @property
    def available(self) -> bool:
        return True

    def chat(self, messages: list[dict[str, str]], *, max_tokens: int = 1500,
             temperature: float | None = None) -> str:
        raise NotImplementedError


class OfflineProvider(BaseProvider):
    """LLM을 쓰지 않는다. 호출부는 available=False 를 보고 규칙 기반 경로로 간다."""
    name = "offline"

    @property
    def available(self) -> bool:
        return False

    def chat(self, messages, **kw) -> str:  # pragma: no cover - 호출되지 않아야 함
        raise LLMError("오프라인 모드에서는 LLM을 호출하지 않습니다.")


class OpenAICompatibleProvider(BaseProvider):
    name = "openai_compatible"

    def chat(self, messages, *, max_tokens=1500, temperature=None) -> str:
        if disabled():
            raise LLMError("LLM is disabled for this runtime/request.")
        base = (self.profile.get("base_url") or "").rstrip("/")
        if not base:
            raise LLMError("base_url 이 비어 있습니다.")
        url = base + "/chat/completions"
        body: dict[str, Any] = {
            "model": self.profile.get("model", ""),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": self.profile.get("temperature", 0.2) if temperature is None else temperature,
        }
        body.update(self.profile.get("extra_body") or {})
        headers = request_headers(self.profile)
        try:
            started=time.perf_counter()
            r = httpx.post(url, json=body, headers=headers,
                           timeout=float(self.profile.get("timeout", 120)))
        except httpx.HTTPError as e:
            raise LLMError("모델 서버 연결 실패", f"{type(e).__name__}: {e}") from e
        if r.status_code >= 400:
            raise LLMError(f"모델 서버 HTTP {r.status_code} 오류", r.text[:300])
        try:
            payload=r.json()
            content = payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise LLMError("모델 응답 형식 오류", r.text[:300]) from e
        if not isinstance(content, str):
            raise LLMError("모델 응답 형식 오류", r.text[:300])
        if _capture.get() is not None:
            _capture.get().append({'url':url,'request':body,'status_code':r.status_code,'elapsed_seconds':round(time.perf_counter()-started,3),'response':payload})
        # 추론형 모델이 <think> 블록을 내보내는 경우 제거
        return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()


PROVIDERS = {
    "offline": OfflineProvider,
    "openai_compatible": OpenAICompatibleProvider,
}


def get_provider(profile: dict[str, Any]) -> BaseProvider:
    if disabled():
        return OfflineProvider({"provider": "offline"})
    cls = PROVIDERS.get(profile.get("provider", "offline"))
    if cls is None:
        raise LLMError(f"지원하지 않는 provider: {profile.get('provider')}")
    return cls(profile)


def extract_json(text: str) -> Any:
    """모델 응답에서 JSON 객체/배열을 꺼낸다. 코드펜스·앞뒤 설명문을 허용한다."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        s, e = text.find(opener), text.rfind(closer)
        if s != -1 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("모델 응답에서 JSON을 찾지 못함", text[:300])
