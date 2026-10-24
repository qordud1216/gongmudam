"""Browser QA transport to ASGI TestClient, with temporary DBs and no listening server."""
import base64
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
from fastapi.testclient import TestClient
import httpx
from app import (adhoc, config, folder_ai, folder_watch, folders, formfill, knowledge,
                 regulation_registry, seed, store, toolbox, travel_api)


def main():
    with tempfile.TemporaryDirectory(prefix='seomu-toolbox-ui-') as directory:
        root = Path(directory).resolve()
        assert root.is_relative_to(Path(tempfile.gettempdir()).resolve())
        store.DATA = root / 'data'; store.LIBRARY = store.DATA / 'library'; store.DB_PATH = store.DATA / 'seomu.db'
        config.CONFIG_PATH = root / 'config.json'; formfill.OUTPUT = root / 'output'
        travel_api.DB_PATH = root / 'travel.db'; adhoc.DB_PATH = root / 'adhoc.db'
        folders.DB_PATH = root / 'folders.db'; regulation_registry.DB_PATH = root / 'regulation-monitor.db'
        cfg = json.loads(config.EXAMPLE_PATH.read_text(encoding='utf-8'))
        cfg['llm']['active'] = 'offline'; config.save(cfg)
        seed.load_seed(reset=True)
        for module in (travel_api, adhoc, toolbox, folders, knowledge, folder_ai, folder_watch, regulation_registry): module.initialize()
        from app.main import app
        with patch('app.workspace.httpx.get', side_effect=httpx.ConnectError('QA: no model discovery')):
            client = TestClient(app)  # No context manager: no lifespan background workers.
            trip = client.post('/api/travel/cases', json=dict(organization_id='demo-city', work_pattern='일반근무',
                destination='부산', purpose='[합성 v57] 교육', start_date='2026-10-15', end_date='2026-10-17',
                transport='철도', overnight=True, meals_provided=False)).json()
            job = client.post('/api/adhoc/jobs', json=dict(situation='[합성 v57] 교육 희망자 취합', title='[합성 v57] 교육 취합',
                course='AI 교육', event_date='2026-11-06', deadline='2026-10-30', departments=['총무팀'])).json()
            reply = adhoc.workbook(job['settings'], [['총무팀', '가상참석자', '주무관', 'AI 교육', '2026-11-06', '희망']])
            print(json.dumps({'ready': True, 'trip': trip['id'], 'job': job['id'], 'reply': base64.b64encode(reply).decode()}), flush=True)
            for line in sys.stdin:
                req = json.loads(line)
                try:
                    response = client.request(req.get('method', 'GET'), req['path'],
                        content=base64.b64decode(req.get('body', '')), headers=req.get('headers', {}))
                    result = {'id': req['id'], 'status': response.status_code,
                              'headers': {k: v for k, v in response.headers.items() if k.lower() not in ('content-length', 'content-encoding', 'transfer-encoding')},
                              'body': base64.b64encode(response.content).decode()}
                except Exception as exc:
                    result = {'id': req['id'], 'error': str(exc)}
                print(json.dumps(result), flush=True)
            client.close()
        if store._conn: store._conn.close(); store._conn = None


if __name__ == '__main__':
    main()
