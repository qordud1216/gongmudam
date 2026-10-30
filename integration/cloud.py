"""Single-operator, no-LLM cloud entrypoint with an externally mounted data volume."""
from contextlib import asynccontextmanager
import fcntl
import os
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]


def release_metadata():
    path = ROOT / 'development-release.json'
    if not path.is_file():
        if os.environ.get('GONGMUDAM_DEVELOPMENT') == '1':
            return {'release_id': 'unpackaged-development', 'source_commit': None, 'source_dirty': True}
        raise RuntimeError('Build and verify a development cloud release before starting.')
    from tools.cloud_release import verify_release
    value = verify_release(ROOT)
    if value.get('source_dirty') and os.environ.get('GONGMUDAM_DEVELOPMENT') != '1':
        raise RuntimeError('A dirty development artifact cannot run as a verified release.')
    expected = os.environ.get('GONGMUDAM_RELEASE_ID')
    if expected and expected != value['release_id']:
        raise RuntimeError('Configured Worker/backend release IDs do not match.')
    return value


def create_app():
    os.environ['GONGMUDAM_CLOUD'] = '1'
    os.environ['GONGMUDAM_NO_LLM'] = '1'
    os.environ['GONGMUDAM_PUBLIC'] = '0'
    os.environ['GONGMUDAM_SERVICE_ROOT'] = str(ROOT / 'service')
    data = os.environ.get('GONGMUDAM_DATA_ROOT')
    if not data:
        raise RuntimeError('Mount and explicitly initialize GONGMUDAM_DATA_ROOT before starting.')
    from tools.cloud_release import owned_state
    owned_state(Path(data))
    release = release_metadata()
    image_id = os.environ.get('GONGMUDAM_IMAGE_ID')
    if not re.fullmatch('sha256:[0-9a-f]{64}', image_id or '') and os.environ.get('GONGMUDAM_DEVELOPMENT') != '1':
        raise RuntimeError('Set the immutable image ID using the verified promotion configuration.')
    os.environ['GONGMUDAM_RELEASE_ID'] = release['release_id']
    from integration.cloud_access import OperatorAccess
    access = OperatorAccess(None, release['release_id'])  # Fail closed before importing/starting the app.
    from integration.application import create_app as integrated_app, EmbeddedPages
    app = integrated_app()
    static = app.router.routes.pop()
    native_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(current):
        # Multiple instances must never start background work against this SQLite volume.
        with (Path(data) / 'cloud-runtime.lock').open('a+b') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('Another app/backup already owns this data volume.') from error
            try:
                async with native_lifespan(current):
                    yield
            finally:
                from app import store
                if store._conn is not None:
                    store._conn.close()
                    store._conn = None
                fcntl.flock(lock, fcntl.LOCK_UN)

    app.router.lifespan_context = lifespan

    @app.get('/health/ready')
    def ready():
        from fastapi.responses import JSONResponse
        try:
            owned_state(Path(data))
            for name in ('folders.db', 'seomu.db', 'travel.db', 'adhoc.db', 'calendar.db'):
                path = Path(data) / 'data' / name
                with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as connection:
                    connection.execute('SELECT count(*) FROM sqlite_schema').fetchone()
        except (OSError, ValueError, sqlite3.Error):
            return JSONResponse({'status': 'not_ready', 'release_id': release['release_id']}, 503)
        return {'status': 'ready', 'release_id': release['release_id'],
                'source_commit': release.get('source_commit'), 'image_id': image_id,
                'data_format': 1, 'llm_enabled': False}

    @app.get('/api/cloud/status')
    def cloud_status():
        return {'mode': 'operator-private-no-llm', 'release_id': release['release_id'],
                'source_commit': release.get('source_commit'), 'development': bool(release.get('source_dirty')),
                'image_id': image_id,
                'requires_origin_pc': False, 'llm_enabled': False, 'shared_demo': False,
                'automatic_source_updates': False,
                'capabilities': {'agency_directory': True, 'source_search': True, 'browser_upload': True,
                                 'pc_folder_sync': False, 'windows_image_ocr': sys.platform == 'win32'},
                'notice': '운영자 전용 · LLM 미사용. PC 폴더는 업로드 사본이며 자동 동기화되지 않습니다. Linux에서는 사진 OCR 대신 원본 대조·수동 입력을 사용하세요.'}

    app.router.routes.append(static)
    app.add_middleware(EmbeddedPages, injection=b'<script src="/desktop/cloud.js" defer></script>', include_desktop=True)
    access.app = app
    return access
