import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app import folder_inputs as inputs, folders

class FolderInputsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patches=[patch.object(inputs,'ROOT',self.root),patch.object(folders,'DB_PATH',self.root/'folders.db')]
        for p in self.patches:p.start()
        folders.initialize();self.app=FastAPI();self.app.state.public_demo=True;self.app.include_router(inputs.router)
        self.client=TestClient(self.app)
    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def post(self,paths=None,content=None,consent=True):
        return self.client.post('/api/folders/uploads',data={'name':'합성 교육자료','paths':json.dumps(paths or ['교육/안내.txt']),'public_consent':str(consent).lower()},files=[('files',('안내.txt',content or '업무명: 합성 교육\n연도: 2026\n개최일: 2026-11-06'.encode(),'text/plain'))])
    def test_upload_creates_real_library_and_extracts_text(self):
        r=self.post();self.assertEqual(r.status_code,201,r.text);v=r.json()
        self.assertEqual(v['summary']['files'],1);self.assertEqual(v['summary']['projects'],1)
        self.assertTrue(v['files'][0]['units']);self.assertTrue(Path(v['files'][0]['path']).is_relative_to(self.root/'synthetic-folders/uploads'))
    def test_traversal_and_windows_names_rejected(self):
        for path in ['../out.txt','A/../out.txt','C:/out.txt','/out.txt','A\\out.txt','A/CON.txt','A/.secret.txt','A/run.exe','A/x:ads.txt']:
            with self.subTest(path=path):self.assertEqual(self.post([path]).status_code,422)
    def test_public_requires_consent(self):self.assertEqual(self.post(consent=False).status_code,422)
    def test_mismatched_paths(self):self.assertEqual(self.post(['A/a.txt','A/b.txt']).status_code,422)
    def test_size_limit_cleans_incomplete_upload(self):
        self.assertEqual(self.post(content=b'x'*(folders.MAX_BYTES+1)).status_code,413)
        self.assertEqual(list((self.root/'synthetic-folders/uploads').iterdir()),[])
    def test_public_cannot_open_native_dialog(self):
        with patch.object(inputs.subprocess,'run') as launch:
            self.assertEqual(self.client.post('/api/folders/choose-local',headers={'origin':'http://testserver'}).status_code,403);launch.assert_not_called()
    def test_tunnel_host_cannot_open_native_dialog(self):
        self.app.state.public_demo=False
        with TestClient(self.app,client=('127.0.0.1',1234),base_url='https://public.example') as c,patch.object(inputs.subprocess,'run') as launch:
            self.assertEqual(c.post('/api/folders/choose-local',headers={'origin':'https://public.example'}).status_code,403);launch.assert_not_called()
    def test_missing_origin_cannot_open_dialog(self):
        self.app.state.public_demo=False
        with TestClient(self.app,client=('127.0.0.1',1234),base_url='http://127.0.0.1:8766') as c:
            self.assertEqual(c.post('/api/folders/choose-local').status_code,403)
    @unittest.skipUnless(os.name == 'nt', 'Native folder dialog success requires Windows; cloud uploads are tested separately.')
    def test_local_cancel_returns_without_connecting(self):
        self.app.state.public_demo=False
        with TestClient(self.app,client=('127.0.0.1',1234),base_url='http://127.0.0.1:8766') as c,patch.object(inputs.subprocess,'run') as launch:
            launch.return_value.returncode=0;launch.return_value.stdout=b'{"path":""}'
            r=c.post('/api/folders/choose-local',headers={'origin':'http://127.0.0.1:8766'})
            self.assertEqual(r.status_code,200);self.assertTrue(r.json()['cancelled']);launch.assert_called_once()

if __name__=='__main__':unittest.main()
