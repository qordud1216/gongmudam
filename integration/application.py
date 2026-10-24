"""Same-origin desktop and existing service, with a separate public runtime."""
from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / 'desktop'
INJECTION = (b'<link rel="stylesheet" href="/desktop/embedded.css">'
             b'<script src="/desktop/embedded.js" defer></script>')


def desktop_asset(name: str) -> Path | None:
    candidate = (DESKTOP / name).resolve()
    if not candidate.is_relative_to(DESKTOP.resolve()) or not candidate.is_file():
        return None
    if candidate.parent == DESKTOP and candidate.suffix in {'.html', '.css', '.js'}:
        return candidate
    if candidate.is_relative_to(DESKTOP / 'assets') and candidate.suffix in {'.svg', '.png', '.woff2', '.txt'}:
        return candidate
    return None


class EmbeddedPages:
    """Inject a browser adapter without editing archived HTML or buffering downloads."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        html = False
        buffered = []

        async def adapted(message):
            nonlocal html
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                html = (not scope['path'].startswith('/desktop/') and
                        any(k.lower() == b'content-type' and b'text/html' in v for k, v in headers))
                updated = []
                for key, value in headers:
                    if html and key.lower() == b'content-length':
                        continue
                    if key.lower() == b'content-security-policy':
                        value = value.replace(b"frame-ancestors 'none'", b"frame-ancestors 'self'")
                        if scope['path'] == '/toolbox.html':
                            value = (b"default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; "
                                     b"worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
                                     b"img-src 'self' data: blob:; connect-src 'self' blob:; "
                                     b"font-src 'self'; frame-ancestors 'self'; base-uri 'self'; object-src 'none'")
                    updated.append((key, value))
                message = {**message, 'headers': updated}
            elif message['type'] == 'http.response.body' and html:
                buffered.append(message.get('body', b''))
                if message.get('more_body'):
                    return
                body = b''.join(buffered)
                body = body.replace(b'</head>', INJECTION + b'</head>', 1)
                message = {**message, 'body': body}
            await send(message)
        await self.app(scope, receive, adapted)


class PublicModelBudget:
    """One shared budget includes the model check routes added after the old demo."""
    def __init__(self, app, limit=30, window=3600):
        self.app = app
        self.limit = limit
        self.window = window
        self.calls = deque()
        self.semaphore = asyncio.Semaphore(1)

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '').rstrip('/')
        guarded = scope['type'] == 'http' and scope.get('method') == 'POST' and (
            path in {'/api/ask', '/api/local-ai/run', '/api/local-ai/failure-check',
                     '/api/settings/llm/test', '/api/workspace/model-check'} or
            path.endswith(('/prefill', '/ai-runs')))
        if not guarded:
            return await self.app(scope, receive, send)
        now = time.monotonic()
        while self.calls and now - self.calls[0] > self.window:
            self.calls.popleft()
        if len(self.calls) >= self.limit or self.semaphore.locked():
            from starlette.responses import JSONResponse
            return await JSONResponse({'detail': '공유 AI가 사용 중이거나 시연 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.'},
                                      status_code=429, headers={'Retry-After': '60'})(scope, receive, send)
        await self.semaphore.acquire()
        self.calls.append(now)
        try:
            return await self.app(scope, receive, send)
        finally:
            self.semaphore.release()


def permit_bundled_public_sources(service: Path, folders, original_roots):
    """Public documents are readable; arbitrary PC directories stay forbidden."""
    bundle = json.loads((service / 'submission-data/knowledge.json').read_text(encoding='utf-8'))
    parents = set()
    for source in bundle['sources']:
        path = service / source['asset']
        if source.get('reference_kind') == 'system_manual':
            path = service / 'data/manuals' / (source['sha256'] + '.pdf')
        parents.add(path.resolve().parent)
    restricted = folders.roots_checked

    def checked(values):
        output = []
        for value in values:
            path = Path(value)
            if path.is_absolute() and path.resolve() in parents:
                output.extend(original_roots([value]))
            else:
                output.extend(restricted([value]))
        return output
    folders.roots_checked = checked


def validate_public_config(candidate, baseline, previous, validator):
    """Only the app-managed selection counter may vary alongside the allowed model."""
    value = copy.deepcopy(candidate)
    original = copy.deepcopy(baseline)
    before = previous.get('llm', {})
    expected = int(before.get('_selection_revision', 0)) + int(value['llm'].get('active') != before.get('active'))
    revision = value['llm'].get('_selection_revision', 0)
    if type(revision) is not int or revision != expected:
        raise ValueError('모델 선택 상태가 바뀌었습니다. 최신 설정을 다시 확인하세요.')
    value['llm'].pop('_selection_revision', None)
    original['llm'].pop('_selection_revision', None)
    validator(value, original)


def ensure_demo_library(service, folders):
    marker = service / 'public-demo.json'
    if not marker.is_file():
        raise RuntimeError('A separate public demo marker is required.')
    definition = json.loads(marker.read_text(encoding='utf-8'))
    if definition.get('private_data_isolated') is not True:
        raise RuntimeError('Private data must not be exposed as a public demo.')
    folders.initialize()
    with folders.db() as connection:
        exists = connection.execute('SELECT 1 FROM libraries WHERE id=?', (definition.get('folder_library_id', ''),)).fetchone()
    if exists:
        return
    incoming = service / 'synthetic-folders/추가회신'
    incoming.mkdir(parents=True, exist_ok=True)
    library = folders.connect(folders.Connect(name='[합성] 공개 교육 자료', roots=[str(incoming)],
        situation='공공 AI 교육 안내와 회신을 정리하는 공개 합성 사례입니다.'))
    definition['folder_library_id'] = library['id']
    temp = marker.with_suffix('.tmp')
    temp.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(marker)


def create_app():
    service = Path(os.environ.get('GONGMUDAM_SERVICE_ROOT', str(ROOT / 'service'))).resolve()
    public = os.environ.get('GONGMUDAM_PUBLIC') == '1'
    if not (service / 'app/main.py').is_file():
        raise RuntimeError('Run prepare_public_runtime.py before starting Gongmudam.')
    sys.path.insert(0, str(service))
    from app import folders, config
    original_roots = folders.roots_checked
    if public:
        from app import public_demo
        ensure_demo_library(service, folders)
        baseline = config.load()
        native_save = config.save
        app = public_demo.create_app()
        def save_public(value):
            validate_public_config(value, baseline, config.load(), public_demo.validate_config)
            native_save(value)
        config.save = save_public
        permit_bundled_public_sources(service, folders, original_roots)
    else:
        from app.main import app
    from desktop.agency_directory import AgencyDirectory
    from fastapi import HTTPException
    from fastapi.responses import FileResponse, RedirectResponse
    directory = AgencyDirectory(DESKTOP / 'data/agencies-v1.sqlite')
    # Existing business routes remain at their original URLs. Root static mount stays last.
    static = app.router.routes.pop()
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, 'path', None) != '/']

    @app.get('/', include_in_schema=False)
    def home():
        return RedirectResponse('/desktop/?variant=B', status_code=307)

    @app.get('/desktop/', include_in_schema=False)
    def desktop():
        return FileResponse(DESKTOP / 'index.html')

    @app.get('/desktop/{name:path}', include_in_schema=False)
    def asset(name: str):
        path = desktop_asset(name)
        if path is None:
            raise HTTPException(404, '파일을 찾지 못했습니다.')
        return FileResponse(path)

    @app.get('/api/agencies')
    def agencies(q: str = '', page: int = 1, limit: int = 8):
        try:
            return directory.search(q, page, limit)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.get('/api/agencies/{code}')
    def agency(code: str):
        try:
            return directory.detail(code)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except KeyError:
            raise HTTPException(404, '기관코드를 찾지 못했습니다.') from None

    @app.get('/api/gongmudam/status')
    def status():
        return {'status': 'ok', 'service_version': 'v69', 'desktop_connected': True,
                'public_demo': public, 'private_data_isolated': public,
                'requires_origin_pc': True, 'shared_demo': public}

    app.router.routes.append(static)
    app.add_middleware(EmbeddedPages)
    if public:
        app.add_middleware(PublicModelBudget)
    return app
