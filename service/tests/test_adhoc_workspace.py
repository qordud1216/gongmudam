import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import adhoc, adhoc_workspace, folders


class AdhocWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_db = self.root / 'adhoc.db'
        self.folder_db = self.root / 'folders.db'
        self.job_patch = patch.object(adhoc, 'DB_PATH', self.job_db)
        self.folder_patch = patch.object(folders, 'DB_PATH', self.folder_db)
        self.job_patch.start(); self.folder_patch.start()
        adhoc.initialize()
        app = FastAPI(); app.include_router(adhoc.router); app.include_router(folders.router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close(); self.job_patch.stop(); self.folder_patch.stop(); self.tmp.cleanup()

    def insert_job(self, key='job-1'):
        with adhoc.db() as c:
            c.execute('INSERT INTO jobs VALUES(?,?,?,?)', (key, 1, json.dumps({'title': 'Job'}), 'now'))

    def put_libraries(self, libraries):
        with sqlite3.connect(self.folder_db) as c:
            c.execute('CREATE TABLE libraries(id TEXT PRIMARY KEY,version INTEGER NOT NULL,payload TEXT NOT NULL)')
            for key, version, payload in libraries:
                c.execute('INSERT INTO libraries VALUES(?,?,?)', (key, version, json.dumps(payload)))

    def get(self, key='job-1'):
        return self.client.get(f'/api/adhoc/jobs/{key}/related-folders')

    def test_missing_folder_database_is_empty_without_creating_it(self):
        self.insert_job()
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'job_id': 'job-1', 'linked': [], 'available': []})
        self.assertFalse(self.folder_db.exists())

    def test_legacy_folder_database_without_libraries_table_is_empty(self):
        self.insert_job()
        sqlite3.connect(self.folder_db).close()
        self.assertEqual(self.get().json()['available'], [])

    def test_projects_are_distinct_and_only_exact_job_links_are_used(self):
        self.insert_job()
        linked = {'id': 'p1', 'name': 'Same', 'links': [
            {'job_id': 'job-1', 'title': 'stale title', 'url': '/wrong'},
            {'job_id': 'job-1', 'title': 'duplicate'}]}
        payloads = [
            ('lib/one', 4, {'name': 'Same lib', 'projects': {'p1': linked, 'p2': {'name': 'Same', 'links': [{'job_id': 'old'}]}},
                'files': {'f1': {'name': 'present.txt', 'project_ids': ['p1'], 'present': True, 'changed': True},
                          'f2': {'name': 'gone.txt', 'project_ids': ['p1'], 'present': False},
                          'f3': {'name': 'other.txt', 'project_ids': ['p2'], 'present': True}}}),
            ('lib-two', 2, {'name': 'Same lib', 'projects': {'p1': {'name': 'Same', 'links': []}}, 'files': {}}),
        ]
        self.put_libraries(payloads)
        result = self.get().json()
        self.assertEqual(len(result['linked']), 1)
        item = result['linked'][0]
        self.assertEqual((item['library_id'], item['project_id'], item['file_count'], item['missing_count']), ('lib/one', 'p1', 1, 1))
        self.assertEqual(item['files'], [
            {'id': 'f1', 'name': 'present.txt', 'present': True, 'changed': True},
            {'id': 'f2', 'name': 'gone.txt', 'present': False, 'changed': False}])
        self.assertEqual(item['href'], 'folders.html#lib%2Fone')
        self.assertEqual(len(result['available']), 2)
        self.assertEqual({(p['library_id'], p['project_id']) for p in result['available']}, {('lib/one', 'p2'), ('lib-two', 'p1')})
        self.assertNotIn('stale title', json.dumps(result))

    def test_read_does_not_mutate_either_database_and_unknown_job_is_404(self):
        self.insert_job()
        self.put_libraries([('lib', 1, {'name': 'Library', 'projects': {}, 'files': {}})])
        before_folder = self.folder_db.read_bytes()
        with adhoc.db() as c:
            before_job = tuple(c.execute('SELECT * FROM jobs').fetchone())
            before_exports = c.execute('SELECT count(*) FROM exports').fetchone()[0]
        self.assertEqual(self.get().status_code, 200)
        self.assertEqual(self.folder_db.read_bytes(), before_folder)
        with adhoc.db() as c:
            self.assertEqual(tuple(c.execute('SELECT * FROM jobs').fetchone()), before_job)
            self.assertEqual(c.execute('SELECT count(*) FROM exports').fetchone()[0], before_exports)
        self.assertEqual(self.get('missing').status_code, 404)

    def test_link_post_is_visible_in_reverse_lookup_without_touching_job_state(self):
        self.insert_job()
        folders.initialize()
        c = sqlite3.connect(self.folder_db)
        try:
            payload = {'name': 'Library', 'projects': {'p': {'id': 'p', 'name': 'Project', 'links': []}}, 'files': {}, 'roots': []}
            c.execute('INSERT INTO libraries VALUES(?,?,?)', ('lib', 1, json.dumps(payload)))
            c.commit()
        finally:
            c.close()
        before_folder = self.folder_db.read_bytes()
        with adhoc.db() as c:
            job_before = tuple(c.execute('SELECT * FROM jobs').fetchone())
            workflow_before = tuple(c.execute('SELECT * FROM job_workflows WHERE job_id=?', ('job-1',)).fetchone()) if c.execute('SELECT count(*) FROM job_workflows WHERE job_id=?', ('job-1',)).fetchone()[0] else None
            exports_before = c.execute('SELECT count(*) FROM exports WHERE job_id=?', ('job-1',)).fetchone()[0]
        response = self.client.post('/api/folders/libraries/lib/projects/p/links', json={'version': 1, 'job_id': 'job-1'})
        self.assertEqual(response.status_code, 200, response.text)
        result = self.get().json()
        self.assertEqual([(p['library_id'], p['project_id']) for p in result['linked']], [('lib', 'p')])
        self.assertEqual(result['linked'][0]['files'], [])
        self.assertEqual(result['available'], [])
        with adhoc.db() as c:
            self.assertEqual(tuple(c.execute('SELECT * FROM jobs').fetchone()), job_before)
            workflow_after = tuple(c.execute('SELECT * FROM job_workflows WHERE job_id=?', ('job-1',)).fetchone()) if c.execute('SELECT count(*) FROM job_workflows WHERE job_id=?', ('job-1',)).fetchone()[0] else None
            self.assertEqual(workflow_after, workflow_before)
            self.assertEqual(c.execute('SELECT count(*) FROM exports WHERE job_id=?', ('job-1',)).fetchone()[0], exports_before)
        c = sqlite3.connect(self.folder_db)
        try:
            self.assertEqual(c.execute('SELECT version FROM libraries WHERE id=?', ('lib',)).fetchone()[0], 2)
        finally:
            c.close()
        self.assertNotEqual(self.folder_db.read_bytes(), before_folder)


if __name__ == '__main__':
    unittest.main()
