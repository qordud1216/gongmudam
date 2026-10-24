import hashlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import folders, folder_scan, folder_scan_io, folder_watch, knowledge


class FolderScanTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / '원본'
        self.source.mkdir()
        self.db_patch = patch.object(folders, 'DB_PATH', self.root / 'folders.db')
        self.db_patch.start()
        folders.initialize()
        folder_scan.initialize()
        knowledge.initialize()
        folder_watch.initialize()
        app = FastAPI()
        app.include_router(folders.router)
        app.include_router(folder_scan.router)
        self.client = TestClient(app, base_url='http://127.0.0.1:8799', client=('127.0.0.1', 1234))
        self.headers = {'Origin': 'http://127.0.0.1:8799'}

    def tearDown(self):
        folder_scan.stop()
        self.client.close()
        self.db_patch.stop()
        self.temp.cleanup()

    def start(self, **overrides):
        body = {'name': '직접 연결 자료함', 'roots': [str(self.source)]} | overrides
        r = self.client.post('/api/folders/scan-jobs', json=body, headers=self.headers)
        self.assertEqual(r.status_code, 202, r.text)
        return r.json()

    def status(self, job):
        r = self.client.get(f"/api/folders/scan-jobs/{job['id']}")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def wait(self, job, states=('completed', 'failed', 'cancelled'), timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.status(job)
            if value['status'] in states:
                return value
            threading.Event().wait(.02)
        self.fail(f"scan job did not finish: {self.status(job)}")

    def library(self, key):
        r = self.client.get(f'/api/folders/libraries/{key}')
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_scans_more_than_legacy_file_and_byte_limits_without_changing_originals(self):
        originals = {}
        for n in range(304):
            p = self.source / f'{n:03}.txt'
            p.write_text('짧은 파일\n', encoding='utf-8')
            originals[p] = (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for n in range(7):
            p = self.source / f'큰문서{n}.txt'
            chunk = '큰 문서 본문\n'.encode('utf-8')
            p.write_bytes((chunk * (6 * 1024 * 1024 // len(chunk) + 1))[:6 * 1024 * 1024])
            originals[p] = (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        job = self.start()
        result = self.wait(job)
        self.assertEqual(result['status'], 'completed', result)
        data = self.library(result['library_id'])
        self.assertEqual(len(data['files']), 311)
        self.assertEqual(data['scan_mode'], folder_scan_io.PROFILE)
        self.assertTrue(all(f['root'] == str(self.source) for f in data['files']))
        for f in data['files']:
            p = Path(f['path'])
            self.assertEqual(f['sha256'], originals[p][0])
            self.assertEqual(p.stat().st_mtime_ns, originals[p][1])
            if p.name.startswith('큰문서'):
                self.assertLessEqual(sum(len(u['text']) for u in f['units']), 512_000)
        self.assertFalse((self.root / 'data' / 'folder-uploads').exists())

    def test_progress_is_monotonic_and_single_bad_file_does_not_stop_job(self):
        (self.source / 'broken.docx').write_bytes(b'abc')
        (self.source / 'good.txt').write_text('행사명: 봄 행사\n연도: 2026\n개최일: 2026-04-10\n주관부서: 총무팀', encoding='utf-8')
        seen = []
        original = folder_scan_io.collect

        def collect(*args, **kwargs):
            callback = kwargs['progress']

            def record(state):
                seen.append(state.copy())
                callback(state)

            kwargs['progress'] = record
            return original(*args, **kwargs)

        with patch.object(folder_scan_io, 'collect', side_effect=collect):
            result = self.wait(self.start())
        self.assertEqual(result['status'], 'completed', result)
        self.assertTrue(any(a['phase'] == 'discovering' for a in seen))
        self.assertTrue(any(a['phase'] == 'reading' for a in seen))
        self.assertTrue(any(a['phase'] == 'saving' for a in seen))
        for key in ('discovered', 'processed', 'bytes_read'):
            values = [s[key] for s in seen]
            self.assertEqual(values, sorted(values), key)
        files = self.library(result['library_id'])['files']
        self.assertTrue(next(f for f in files if f['name'] == 'broken.docx')['limited'])
        self.assertEqual(len(files), 2)

    def test_rescan_reuses_unchanged_hash_and_keeps_confirmed_classification(self):
        p = self.source / '계획.txt'
        p.write_text('행사명: 봄 행사\n연도: 2026\n개최일: 2026-04-10\n', encoding='utf-8')
        other = self.source / '추가.txt'
        other.write_text('변경 전 본문', encoding='utf-8')
        initial = self.wait(self.start())
        lib = self.library(initial['library_id'])
        f = lib['files'][0]
        project_id = lib['projects'][0]['id']
        r = self.client.patch(f"/api/folders/libraries/{lib['id']}/files/{f['id']}",
                              json={'version': lib['version'], 'project_ids': [project_id], 'reason': '담당 업무 자료로 확인'})
        self.assertEqual(r.status_code, 200, r.text)
        lib = r.json()
        before = p.read_bytes()
        result = self.wait(self.start(library_id=lib['id'], version=lib['version']))
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['reused'], 2)
        rescanned = self.library(lib['id'])
        self.assertTrue(rescanned['files'][0]['confirmed'])
        self.assertEqual(rescanned['files'][0]['project_ids'], [project_id])
        self.assertEqual(p.read_bytes(), before)
        other.write_text('변경한 본문', encoding='utf-8')
        result = self.wait(self.start(library_id=lib['id'], version=rescanned['version']))
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['reused'], 1)

    def test_cancel_and_version_conflict_leave_library_unchanged(self):
        (self.source / 'a.txt').write_text('행사명: 봄 행사\n연도: 2026\n개최일: 2026-04-10\n주관부서: 총무팀', encoding='utf-8')
        initial = self.wait(self.start())
        lib = self.library(initial['library_id'])
        entered, release = threading.Event(), threading.Event()
        original = folder_scan_io.collect

        def gated(*args, **kwargs):
            incoming = original(*args, **kwargs)
            entered.set()
            release.wait(5)
            return incoming

        with patch.object(folder_scan_io, 'collect', side_effect=gated):
            job = self.start(library_id=lib['id'], version=lib['version'])
            self.assertTrue(entered.wait(5))
            self.client.post(f"/api/folders/scan-jobs/{job['id']}/cancel", headers=self.headers)
            release.set()
            cancelled = self.wait(job)
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertEqual(self.library(lib['id'])['version'], lib['version'])

        entered.clear(); release.clear()
        with patch.object(folder_scan_io, 'collect', side_effect=gated):
            job = self.start(library_id=lib['id'], version=lib['version'])
            self.assertTrue(entered.wait(5))
            current = self.library(lib['id'])
            update = self.client.patch(f"/api/folders/libraries/{lib['id']}/projects/{current['projects'][0]['id']}",
                                       json={'version': current['version'], 'name': '변경된 업무명'})
            self.assertEqual(update.status_code, 200, update.text)
            release.set()
            failed = self.wait(job)
        self.assertEqual(failed['status'], 'failed')
        final = self.library(lib['id'])
        self.assertEqual(final['version'], current['version'] + 1)
        self.assertEqual(final['projects'][0]['name'], '변경된 업무명')

    def test_only_one_active_job_and_loopback_origin_guards(self):
        gate = threading.Event()
        original = folder_scan_io.collect

        def blocked(*args, **kwargs):
            gate.wait(5)
            return original(*args, **kwargs)

        with patch.object(folder_scan_io, 'collect', side_effect=blocked):
            first = self.start()
            second = self.client.post('/api/folders/scan-jobs', json={'name': '다른 자료함', 'roots': [str(self.source)]}, headers=self.headers)
            self.assertEqual(second.status_code, 409, second.text)
            gate.set()
            self.assertEqual(self.wait(first)['status'], 'completed')
        for base_url, headers in (
            ('http://example.com:8799', {'Origin': 'http://example.com:8799'}),
            ('http://127.0.0.1:8799', {'Origin': 'https://tunnel.example'}),
            ('http://127.0.0.1:8799', {'Origin': 'http://127.0.0.1:8799', 'X-Forwarded-For': '203.0.113.1'}),
        ):
            with TestClient(self.client.app, base_url=base_url, client=('127.0.0.1', 1234)) as client:
                denied = client.post('/api/folders/scan-jobs', json={'name': '거부 자료함', 'roots': [str(self.source)]}, headers=headers)
                self.assertEqual(denied.status_code, 403)

    def test_interrupted_jobs_recover_without_publishing(self):
        key = 'interrupted-test'
        payload = {'id': key, 'status': 'running', 'input': {'name': '자료함', 'roots': [str(self.source)]},
                   'updated_at': 'before', 'library_id': None}
        with folders.db() as c:
            c.execute('INSERT INTO folder_scan_jobs VALUES(?,?,?)', (key, 'running', folders.encode(payload)))
        folder_scan.initialize(recover=True)
        with folders.db() as c:
            row = c.execute('SELECT status,payload FROM folder_scan_jobs WHERE id=?', (key,)).fetchone()
        self.assertEqual(row['status'], 'interrupted')
        self.assertEqual(json.loads(row['payload'])['status'], 'interrupted')
        with folders.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM libraries').fetchone()[0], 0)

    def test_utf8_sample_boundary_keeps_multilingual_event_name(self):
        from io import BytesIO
        raw = b' ' * 65_535 + '행사명: 경계 테스트\n연도: 2026'.encode('utf-8')
        units, _, _ = folder_scan_io.text_preview(BytesIO(raw))
        self.assertTrue(any('행사명: 경계 테스트' in unit['text'] for unit in units), units[:2])

    def test_duplicate_summary_caps_id_list_but_counts_all_duplicates(self):
        for n in range(1000):
            (self.source / f'{n:04}.txt').write_text('동일한 내용', encoding='utf-8')
        result = self.wait(self.start(), timeout=30)
        self.assertEqual(result['status'], 'completed', result)
        files = self.library(result['library_id'])['files']
        self.assertEqual(len(files), 1000)
        self.assertTrue(all(f.get('duplicate_count') == 999 for f in files))
        self.assertTrue(all(len(f.get('duplicates', [])) <= 100 for f in files))

    def test_partial_rescan_preserves_unvisited_files_and_confirmation(self):
        for name in ('a.txt', 'b.txt', 'c.txt'):
            (self.source / name).write_text('행사명: 봄 행사\n연도: 2026\n개최일: 2026-04-10\n주관부서: 총무팀', encoding='utf-8')
        initial = self.wait(self.start())
        lib = self.library(initial['library_id'])
        confirmed_id = next(f['id'] for f in lib['files'] if f['name'] == 'c.txt')
        # A common-material confirmation has no project dependency.
        assigned = self.client.patch(f"/api/folders/libraries/{lib['id']}/files/{confirmed_id}",
                                     json={'version': lib['version'], 'bucket': 'common', 'project_ids': [], 'reason': '공통 서식으로 확인'})
        self.assertEqual(assigned.status_code, 200, assigned.text)
        lib = assigned.json()
        with patch.object(folder_scan_io, 'MAX_FILES', 1):
            partial = self.wait(self.start(library_id=lib['id'], version=lib['version']))
        self.assertEqual(partial['status'], 'completed', partial)
        self.assertTrue(partial['warnings'])
        after = self.library(lib['id'])
        self.assertEqual(after['roots'], lib['roots'])
        old_by_name = {f['name']: f for f in lib['files']}
        new_by_name = {f['name']: f for f in after['files']}
        self.assertEqual(set(new_by_name), set(old_by_name))
        self.assertTrue(new_by_name['b.txt']['present'])
        self.assertTrue(new_by_name['c.txt']['present'])
        self.assertTrue(new_by_name['c.txt']['confirmed'])

    def test_large_direct_file_can_register_as_knowledge_then_detects_mutation(self):
        path = self.source / '큰 참고자료.txt'
        text = '행사명: 대용량 참고자료\n연도: 2026\n' + ('참고 내용입니다.\n' * 500_000)
        path.write_text(text, encoding='utf-8')
        result = self.wait(self.start())
        self.assertEqual(result['status'], 'completed', result)
        lib = self.library(result['library_id'])
        file = lib['files'][0]
        self.assertGreater(file['size'], 5 * 1024 * 1024)
        registered = knowledge.register(lib['id'], knowledge.Register(version=lib['version'], file_ids=[file['id']], kind='참고자료'))
        self.assertEqual(registered['registered'], 1)
        source = registered['sources'][0]
        self.assertTrue(source['current'])
        path.write_text(text + '내용 변경\n', encoding='utf-8')
        self.assertFalse(knowledge.current_source(source))

    def test_folder_watch_direct_profile_dispatches_new_collector(self):
        (self.source / 'watch.txt').write_text('감시 대상', encoding='utf-8')
        result = self.wait(self.start())
        lib = self.library(result['library_id'])
        with folders.db() as c:
            folder_watch.put(c, lib['id'], {'enabled': True, 'profile': '', 'interval': 30, 'pending': {}, 'changes': [], 'blocked': False, 'next_check': 0})
        called = []
        collect = folder_scan_io.collect

        def track(*args, **kwargs):
            called.append(True)
            return collect(*args, **kwargs)

        with patch.object(folder_scan_io, 'collect', side_effect=track):
            folder_watch.scan_one(lib['id'], now=time.time() + 10)
        self.assertTrue(called, 'direct-v63 watch must use folder_scan_io.collect')


if __name__ == '__main__':
    unittest.main()
