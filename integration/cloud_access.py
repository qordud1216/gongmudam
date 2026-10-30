"""Validate Cloudflare Access signatures and restrict this installation to one operator."""
import json
import os
from pathlib import Path
import re

import jwt
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

MAX_BODY = 12 * 1024 * 1024


class OperatorAccess:
    def __init__(self, app, release_id):
        self.app, self.release_id = app, release_id
        team = os.environ.get('GONGMUDAM_ACCESS_TEAM_DOMAIN', '')
        self.audience = os.environ.get('GONGMUDAM_ACCESS_AUD', '')
        self.owner = os.environ.get('GONGMUDAM_OWNER_EMAIL', '').strip().casefold()
        if not re.fullmatch(r'[a-z0-9-]+\.cloudflareaccess\.com', team):
            raise RuntimeError('Configure GONGMUDAM_ACCESS_TEAM_DOMAIN before starting the cloud app.')
        if not re.fullmatch(r'[0-9a-fA-F]{64}', self.audience) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', self.owner):
            raise RuntimeError('Configure the Access application audience and one operator email.')
        self.issuer = 'https://' + team
        fixture = os.environ.get('GONGMUDAM_ACCESS_JWKS_FILE')
        self.keys = jwt.PyJWKSet.from_dict(json.loads(Path(fixture).read_text())) if fixture else None
        self.client = None if fixture else jwt.PyJWKClient(self.issuer + '/cdn-cgi/access/certs',
                                                         cache_keys=True, lifespan=300, timeout=5)

    def authorize(self, token):
        if not token or len(token) > 16384:
            return 401
        try:
            kid = jwt.get_unverified_header(token).get('kid')
            if not isinstance(kid, str) or len(kid) > 128:
                return 401
            key = self.keys[kid].key if self.keys else self.client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=['RS256'], audience=self.audience,
                                issuer=self.issuer, options={'require': ['exp', 'iat', 'iss', 'aud', 'email', 'sub']})
            return 200 if str(claims['email']).casefold() == self.owner else 403
        except (jwt.PyJWTError, KeyError, ValueError, OSError):
            return 401

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path, method = scope['path'].rstrip('/'), scope['method']
        headers = Headers(scope=scope)
        # Liveness has no release, data, user, configuration or readiness details.
        if path == '/health/live' and method in ('GET', 'HEAD'):
            return await JSONResponse({'status': 'alive'}, headers={'Cache-Control': 'no-store'})(scope, receive, send)
        status = await run_in_threadpool(self.authorize, headers.get('Cf-Access-Jwt-Assertion'))
        if status != 200:
            return await JSONResponse({'code': 'operator_auth_required', 'detail': '운영자 인증이 필요합니다.'},
                                      status_code=status, headers={'Cache-Control': 'no-store'})(scope, receive, send)
        async def protected_send(message):
            if message['type'] == 'http.response.start':
                values = [(k, v) for k, v in message.get('headers', [])
                          if k.lower() not in {b'cache-control', b'x-gongmudam-release'}]
                values += [(b'cache-control', b'no-store'),
                           (b'x-gongmudam-release', self.release_id.encode('ascii')),
                           (b'x-content-type-options', b'nosniff'), (b'referrer-policy', b'same-origin')]
                message = {**message, 'headers': values}
            await send(message)
        if method not in ('GET', 'HEAD', 'OPTIONS'):
            from urllib.parse import urlsplit
            origin = headers.get('origin')
            host = headers.get('x-forwarded-host') or headers.get('host', '')
            if origin and (urlsplit(origin).scheme not in ('http', 'https') or urlsplit(origin).netloc != host):
                return await JSONResponse({'detail': '다른 사이트의 요청은 허용하지 않습니다.'}, 403)(scope, receive, protected_send)
            # Bound chunked bodies too, before a parser or handler sees them.
            messages, size = [], 0
            while True:
                message = await receive()
                messages.append(message)
                size += len(message.get('body', b''))
                if size > MAX_BODY:
                    return await JSONResponse({'detail': '업로드 요청은 12MB 이하여야 합니다.'}, 413)(scope, receive, protected_send)
                if message['type'] != 'http.request' or not message.get('more_body'):
                    break
            original_receive = receive
            iterator = iter(messages)
            async def replay():
                return next(iterator, None) or await original_receive()
            receive = replay
        blocked_model = path.startswith('/api/local-ai') or (method == 'POST' and (
            path in {'/api/workspace/model-check', '/api/settings/llm/test', '/api/llm/test'} or
            path.endswith(('/prefill', '/ai-runs'))))
        if blocked_model:
            return await JSONResponse({'code': 'llm_disabled', 'detail': '이 릴리즈는 LLM을 사용하지 않습니다.'}, 503)(scope, receive, protected_send)
        if path.startswith('/api/regulations') and method not in ('GET', 'HEAD', 'OPTIONS'):
            return await JSONResponse({'code': 'source_update_requires_separate_review',
                                       'detail': '이 릴리즈의 규정 갱신·검수는 코드 배포와 별도 절차로 진행합니다.'}, 409)(scope, receive, protected_send)
        if path == '/api/folders/choose-local':
            return await JSONResponse({'code': 'browser_upload_required',
                                       'detail': '클라우드에서는 브라우저의 폴더 업로드를 사용하세요. PC 자동 동기화는 지원하지 않습니다.'}, 403)(scope, receive, protected_send)
        await self.app(scope, receive, protected_send)
