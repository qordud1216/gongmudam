"""Reference attachment isolation, version checks, original bytes and repeat safety."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import adhoc, regulation_registry, toolbox, travel_api

PDF = b'%PDF-1.4\nsynthetic reference, never parsed or executed'


class ToolboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(m, 'DB_PATH', Path(self.tmp.name) / name)
                        for m, name in ((adhoc, 'adhoc.db'), (travel_api, 'travel.db'), (regulation_registry, 'monitor.db'))]
        for p in self.patches: p.start()
        travel_api.initialize(); adhoc.initialize(); toolbox.initialize()
        app = FastAPI()
        for router in (travel_api.router, adhoc.router, toolbox.router): app.include_router(router)
        self.client = TestClient(app)
        self.trip = self.client.post('/api/travel/cases', json=dict(organization_id='demo-city', work_pattern='일반근무',
            destination='부산', purpose='[합성] 교육', start_date='2026-10-15', end_date='2026-10-17',
            transport='철도', overnight=True, meals_provided=False)).json()
        self.job = self.client.post('/api/adhoc/jobs', json=dict(situation='[합성] 교육 참석 희망자 취합',
            title='[합성] 교육 취합', course='AI 교육', event_date='2026-11-06', deadline='2026-10-30', departments=['총무팀'])).json()

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def url(self, kind='adhoc', ident=None):
        return f"/api/toolbox/{kind}/{ident or (self.trip if kind == 'travel' else self.job)['id']}/attachments"

    def put(self, kind='adhoc', name='참고.pdf', raw=PDF, version=1, status=201, ident=None):
        r = self.client.post(self.url(kind, ident), data={'version': version, 'source_tool': 'pdfmerge'},
                             files={'file': (name, raw, 'application/octet-stream')})
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    def test_targets_and_nonexistent_owner_never_fall_through(self):
        found = self.client.get('/api/toolbox/targets').json()['targets']
        self.assertEqual({(x['kind'], x['id']) for x in found}, {('travel', self.trip['id']), ('adhoc', self.job['id'])})
        self.assertEqual(self.client.get(self.url('travel', self.job['id'])).status_code, 404)
        self.assertEqual(self.client.get('/api/toolbox/other/x/attachments').status_code, 422)
        self.put(ident='missing-owner', status=404)

    def test_reference_preserves_business_versions_and_original(self):
        for kind, before, endpoint in (('travel', self.trip, '/api/travel/cases/'), ('adhoc', self.job, '/api/adhoc/jobs/')):
            saved = self.put(kind, name='../../경로/원본.pdf')
            item = saved['items'][0]
            self.assertEqual(item['filename'], '원본.pdf')
            self.assertEqual(item['sha256'], hashlib.sha256(PDF).hexdigest())
            self.assertEqual(saved['target']['version'], before['version'])
            response = self.client.get(item['original_url'])
            self.assertEqual(response.content, PDF)
            self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertTrue(response.headers['content-disposition'].startswith('attachment;'))
            after = self.client.get(endpoint + before['id']).json()
            self.assertEqual(after['version'], before['version'])
            if kind == 'adhoc':
                self.assertEqual(after['rows'], before['rows'])
                self.assertEqual(after['exports'], before['exports'])
                self.assertEqual(after['workflow']['revision'], before['workflow']['revision'])
            else:
                self.assertEqual(after['review']['transactions'], before['review']['transactions'])
            other = self.client.get(item['original_url'].replace(before['id'], 'missing-owner'))
            self.assertEqual(other.status_code, 404)

    def test_duplicate_parallel_retry_is_one_record_and_history_entry(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.put(), range(2)))
        self.assertEqual(len({r['attachment_id'] for r in results}), 1)
        self.assertEqual(sorted(r['duplicate'] for r in results), [False, True])
        job = self.client.get('/api/adhoc/jobs/' + self.job['id']).json()
        self.assertEqual(sum(r['kind'] == '도구함 참고 파일 첨부' for r in job['history']), 1)

    def test_stale_version_rejected_without_partial_attachment(self):
        self.put(version=9, status=409)
        self.assertEqual(self.client.get(self.url()).json()['items'], [])
        self.assertEqual(self.client.get('/api/adhoc/jobs/' + self.job['id']).json()['version'], 1)

    def test_limits_signatures_and_unsupported_types_leave_no_records(self):
        self.assertEqual(toolbox.checked_file('../../경로/원본\n.pdf', PDF)[0], '원본.pdf')
        for name, raw in (('fake.png', PDF), ('payload.html', b'<script>alert(1)</script>'), ('empty.txt', b'')):
            self.put(name=name, raw=raw, status=422)
        with patch.object(toolbox, 'MAX_BYTES', 20): self.put(status=422)
        self.assertEqual(self.client.get(self.url()).json()['items'], [])

    def test_caps_count_and_total_and_allows_duplicate_at_cap(self):
        first = self.put()
        with patch.object(toolbox, 'MAX_FILES', 1):
            self.put(name='other.txt', raw=b'other', status=422)
            self.assertTrue(self.put()['duplicate'])
        with patch.object(toolbox, 'MAX_TOTAL', len(PDF)):
            self.put(name='other.txt', raw=b'other', status=422)
        self.assertEqual(self.client.get(self.url()).json()['items'][0]['id'], first['attachment_id'])

    def test_idempotent_initialize_and_integrity_failure(self):
        value = self.put('travel')
        toolbox.initialize(); travel_api.initialize(); adhoc.initialize(); toolbox.initialize()
        self.assertEqual(len(self.client.get(self.url('travel')).json()['items']), 1)
        path = value['items'][0]['original_url']
        self.assertEqual(self.client.get(path).content, PDF)
        with travel_api.db() as c:
            c.execute('UPDATE toolbox_attachments SET original=? WHERE id=?', (b'changed', value['attachment_id']))
        self.assertEqual(self.client.get(path).status_code, 409)

    def test_doc_and_archive_outputs_are_stored_without_merging(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as z: z.writestr('content.xml', '<text>합성 문서</text>')
        for ext in ('.zip', '.hwpx', '.odt', '.xlsx'):
            value = self.put(name='결과' + ext, raw=stream.getvalue() + ext.encode())
            self.assertEqual(self.client.get(value['items'][-1]['original_url']).content, stream.getvalue() + ext.encode())
        self.assertEqual(self.client.get('/api/adhoc/jobs/' + self.job['id']).json()['rows'], [])
