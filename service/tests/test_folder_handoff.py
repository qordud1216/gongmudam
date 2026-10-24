import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import folder_inputs, folders
from test_core import Base

class FolderHandoffTest(Base):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'source';self.source.mkdir();(self.source/'note.txt').write_text('업무 목적 자료',encoding='utf-8')
        self.patches=[patch.object(folders,'DB_PATH',self.root/'folders.db'),patch.object(folder_inputs,'ROOT',self.root)]
        for item in self.patches:item.start()
        folders.initialize();self.app=FastAPI();self.app.state.public_demo=False
        self.app.include_router(folders.router);self.app.include_router(folder_inputs.router)
        self.client=TestClient(self.app)
    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()
    def test_connect_and_report_preserve_situation(self):
        text='11월 교육 회신과 결과 보고 자료를 정리합니다.'
        response=self.client.post('/api/folders/libraries',json={'name':'합성 자료함','roots':[str(self.source)],'situation':text})
        self.assertEqual(response.status_code,201,response.text);key=response.json()['id']
        report=self.client.get(f'/api/folders/libraries/{key}/report.json')
        self.assertEqual(report.status_code,200);self.assertEqual(report.json()['situation'],text)
    def test_connect_rejects_long_situation(self):
        response=self.client.post('/api/folders/libraries',json={'name':'합성 자료함','roots':[str(self.source)],'situation':'x'*3001})
        self.assertEqual(response.status_code,422)
    def test_upload_preserves_optional_situation_and_rejects_long_value(self):
        data={'name':'합성 업로드','paths':json.dumps(['교육/안내.txt']),'situation':'참석자 회신을 정리합니다.'}
        response=self.client.post('/api/folders/uploads',data=data,files=[('files',('안내.txt','합성 본문'.encode(),'text/plain'))])
        self.assertEqual(response.status_code,201,response.text);self.assertEqual(response.json()['situation'],data['situation'])
        data['situation']='x'*3001
        response=self.client.post('/api/folders/uploads',data=data,files=[('files',('안내.txt','합성 본문'.encode(),'text/plain'))])
        self.assertEqual(response.status_code,422)
    def test_legacy_library_without_situation_remains_readable(self):
        created=self.client.post('/api/folders/libraries',json={'name':'구버전 자료함','roots':[str(self.source)]})
        self.assertEqual(created.status_code,201,created.text);key=created.json()['id']
        with folders.db() as connection:
            row=connection.execute('SELECT payload FROM libraries WHERE id=?',(key,)).fetchone()
            legacy=json.loads(row['payload']);legacy.pop('situation',None)
            connection.execute('UPDATE libraries SET payload=? WHERE id=?',(folders.encode(legacy),key))
        detail=self.client.get(f'/api/folders/libraries/{key}')
        self.assertEqual(detail.status_code,200);self.assertNotIn('situation',detail.json())

if __name__=='__main__':unittest.main()

