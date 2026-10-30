"""Selected local model discovery and explicit, synthetic response checks.

Opening a page only discovers models. Checks never consume work documents and
their short-lived evidence belongs to one exact selection, not to an engine.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import secrets
import threading
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from . import config, llm

EVIDENCE_TTL = 300
_secret = secrets.token_bytes(32)
_state_lock = threading.Lock()
_check_lock = threading.Lock()
_inflight = None
_last_response = None


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _selection():
    cfg = config.load()
    profile = copy.deepcopy(config.active_profile(cfg))
    extra = profile.get('extra_body') or {}
    model = extra.get('model', profile.get('model')) if isinstance(extra, dict) else profile.get('model')
    identity = [cfg.get('llm', {}).get('_selection_revision', 0), profile, llm.request_headers(profile)]
    token = hmac.new(_secret, json.dumps(identity, ensure_ascii=False, sort_keys=True).encode(), hashlib.sha256).hexdigest()
    return token, profile, model


def _target(profile, model):
    if llm.disabled():
        return "offline", None
    if profile.get('provider', 'offline') == 'offline':
        return 'offline', None
    if profile.get('provider') != 'openai_compatible':
        return 'invalid', None
    try:
        url = urlsplit(profile.get('base_url') or '')
        port = url.port
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment or port == 0:
            return 'invalid', None
        if url.hostname not in ('localhost', '127.0.0.1', '::1'):
            return 'external', None
        if not isinstance(model, str) or not model.strip():
            return 'invalid', None
    except (ValueError, TypeError):
        return 'invalid', None
    return 'local', (profile['base_url'].rstrip('/') + '/models')


def _same_model(expected, actual):
    if not isinstance(expected, str) or not isinstance(actual, str):
        return False
    return expected == actual or (':' not in expected and actual == expected + ':latest') or (':' not in actual and expected == actual + ':latest')


def _connection(profile, model):
    kind, target = _target(profile, model)
    value = dict(state=kind, checked_at=_stamp(), server_responded=False, model_present=None)
    if kind != 'local':
        return value
    try:
        response = httpx.get(target, headers=llm.request_headers(profile), timeout=2, follow_redirects=False)
        value['server_responded'] = True
        if response.status_code in (401, 403):
            value['state'] = 'unauthorized'
        elif response.status_code in (404, 405, 501) or 300 <= response.status_code < 400:
            value['state'] = 'unsupported'
        elif response.status_code != 200:
            value['state'] = 'server_error'
        else:
            payload = response.json()
            models = payload.get('data') if isinstance(payload, dict) else None
            if not isinstance(models, list) or any(not isinstance(item, dict) or not isinstance(item.get('id'), str) for item in models):
                value['state'] = 'invalid_response'
            else:
                value['model_present'] = any(_same_model(model, item['id']) for item in models)
                value['state'] = 'ready' if value['model_present'] else 'model_missing'
    except httpx.HTTPError:
        value['state'] = 'unreachable'
    except (ValueError, TypeError):
        value['state'] = 'invalid_response'
    value['checked_at'] = _stamp()
    return value


def _response_for(token):
    with _state_lock:
        if _inflight == token:
            return dict(state='checking', checked_at=None, message='선택 모델의 시험 응답을 기다리고 있습니다.')
        if _last_response and _last_response['token'] == token:
            value = dict(_last_response['value'])
            if time.monotonic() - _last_response['saved_at'] > EVIDENCE_TTL:
                value.update(state='expired', message='최근 시험 결과가 오래되어 다시 확인이 필요합니다.')
            return value
    return dict(state='unverified', checked_at=None, message='선택한 설정으로 실제 응답을 아직 확인하지 않았습니다.')


def _assert_selection(token):
    if _selection()[0] != token:
        raise HTTPException(409, dict(code='selection_changed', message='모델 선택이나 연결 설정이 바뀌었습니다. 현재 모델을 다시 확인하세요.'))


def snapshot():
    token, profile, model = _selection()
    connection = _connection(profile, model)
    _assert_selection(token)
    with _state_lock:
        in_progress = _inflight is not None
    return dict(selection_id=token, profile=profile['_name'], model=model, offline=connection['state'] == 'offline',
                local=_target(profile, model)[0] == 'local', checked_at=connection['checked_at'], connection=connection,
                response=_response_for(token), check_in_progress=in_progress,
                evidence_ttl_seconds=EVIDENCE_TTL,
                notice='서버·모델 목록 확인과 최근 시험 응답을 구분합니다. 시험 결과는 5분간 유지되며 현재 질문에서 AI를 사용했다는 뜻은 아닙니다.')


def check(selection_id):
    """One synthetic completion; stale selections cannot publish evidence."""
    global _inflight, _last_response
    token, profile, model = _selection()
    if selection_id != token:
        _assert_selection(selection_id)
    if _target(profile, model)[0] != 'local':
        raise HTTPException(422, dict(code='not_local', message='이 확인 기능은 선택한 로컬 모델 서버에만 시험 요청을 보냅니다.'))
    if not _check_lock.acquire(blocking=False):
        raise HTTPException(409, dict(code='check_busy', message='이전 응답 시험을 마무리하고 있습니다. 잠시 후 다시 확인하세요.'))
    try:
        _assert_selection(token)
        with _state_lock:
            _inflight = token
        started = time.perf_counter()
        value = dict(state='failed', checked_at=None, requested_model=model, response_model=None, characters=0,
                     message='시험 요청의 응답을 확인하지 못했습니다.')
        # Keep the selected endpoint/auth/model and JSON-format options. Only a
        # fixed synthetic message and a bounded non-streaming output are sent.
        test_profile = copy.deepcopy(profile)
        extras = test_profile.get('extra_body') or {}
        test_profile['extra_body'] = {k: v for k, v in extras.items() if k not in ('messages', 'stream', 'max_tokens')} if isinstance(extras, dict) else {}
        try:
            timeout = float(test_profile.get('timeout', 60))
            test_profile['timeout'] = min(timeout, 60) if math.isfinite(timeout) and timeout > 0 else 60
        except (TypeError, ValueError):
            test_profile['timeout'] = 60
        try:
            with llm.capture_calls() as calls:
                text = llm.get_provider(test_profile).chat([{'role': 'user', 'content': 'Return only this JSON object: {"ok": true}'}], max_tokens=64, temperature=0)
            if not text.strip():
                value.update(state='empty', message='응답은 도착했지만 확인 가능한 텍스트가 없습니다.')
            elif not calls:
                value.update(state='model_unverified', message='응답은 도착했지만 응답 모델 정보를 확인하지 못했습니다.')
            else:
                request_model = calls[-1]['request'].get('model')
                response_model = calls[-1]['response'].get('model')
                value.update(requested_model=request_model, response_model=response_model if isinstance(response_model, str) else None, characters=len(text))
                if not isinstance(response_model, str) or not response_model:
                    value.update(state='model_unverified', message='응답은 도착했지만 서버가 응답 모델명을 알려주지 않았습니다.')
                elif not _same_model(model, request_model) or not _same_model(model, response_model):
                    value.update(state='model_mismatch', message='선택한 모델과 서버가 보고한 응답 모델이 다릅니다.')
                else:
                    value.update(state='verified', message='선택한 모델의 텍스트 응답과 서버가 보고한 모델명을 확인했습니다.')
        except llm.LLMError:
            pass
        value.update(checked_at=_stamp(), elapsed_seconds=round(time.perf_counter() - started, 3))
        _assert_selection(token)
        with _state_lock:
            _last_response = dict(token=token, value=value, saved_at=time.monotonic())
        return dict(selection_id=token, profile=profile['_name'], model=model, response=value)
    finally:
        with _state_lock:
            _inflight = None
        _check_lock.release()
