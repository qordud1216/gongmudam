"""Archived official excerpts must survive unrelated, higher-scoring notes."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import folders, knowledge, main, official_sources


class CandidateCoverageTest(unittest.TestCase):
    query = '국가공무원이 출장 후 운임과 숙박비 정산을 신청할 때 신청기한과 증거서류는 어떻게 되나요?'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_patch = patch.object(folders, 'DB_PATH', self.root / 'folders.db')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        folders.initialize()
        knowledge.initialize()
        self.docs = self.root / 'docs'
        self.docs.mkdir()
        manifest = json.loads((official_sources.BASE / 'manifest.json').read_text(encoding='utf-8'))
        self.official = next(row for row in manifest
                             if row['title'] == '공무원 여비 규정' and row['article'].startswith('제8조의2('))
        self.original = (official_sources.BASE / 'excerpts' / self.official['filename']).read_bytes()
        self.source = self.docs / '공무원 여비 규정 제8조의2.txt'
        self.source.write_bytes(self.original)
        for number in range(60):
            # These are explicitly reference notes, with no direct rule to cite.
            (self.docs / f'출장 정산 검토 메모 {number:02}.txt').write_text(
                (self.query + '\n') * 3 + '참고 메모입니다. 정산 기준은 별도 원문을 확인하세요.',
                encoding='utf-8')
        self.library = folders.connect(folders.Connect(name='후보 누락 회귀 시험', roots=[str(self.docs)]))
        self.file_ids = {f['name']: f['id'] for f in self.library['files']}
        self.register(list(self.file_ids.values()))
        self.client = TestClient(main.app)  # No lifespan: no background monitors or model startup.
        self.addCleanup(self.client.close)

    def register(self, file_ids):
        for offset in range(0, len(file_ids), 30):
            knowledge.register(self.library['id'], knowledge.Register(
                version=self.library['version'], file_ids=file_ids[offset:offset + 30], kind='참고자료'))

    def ask(self, today='2026-10-20'):
        with patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}), \
             patch.object(knowledge.llm.OfflineProvider, 'chat', side_effect=AssertionError('LLM must stay unused')), \
             patch.object(knowledge.llm.OpenAICompatibleProvider, 'chat', side_effect=AssertionError('LLM must stay unused')):
            response = self.client.post('/api/ask', json={
                'query': self.query, 'knowledge_library_id': self.library['id'], 'today': today})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_direct_official_article_survives_more_than_48_reference_notes(self):
        reply = self.ask()
        self.assertEqual(reply['mode'], 'source_search', reply.get('notice'))
        evidence = reply['knowledge']['evidence']
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['sha256'], self.official['sha256'])
        self.assertEqual(evidence[0]['official']['source_url'], self.official['source_url'])
        self.assertIn(evidence[0]['quote'], self.original.decode('utf-8-sig').replace('\r\n', '\n'))
        self.assertIn('2주일 이내', reply['answer'])
        self.assertIn('증거서류', reply['answer'])

    def test_disabling_the_official_source_keeps_reference_notes_out(self):
        response = self.client.get('/api/knowledge/sources', params={'library_id': self.library['id']})
        self.assertEqual(response.status_code, 200)
        source = next(row for row in response.json() if row.get('official'))
        self.assertTrue(source['current'])
        response = self.client.put(f"/api/knowledge/sources/{source['id']}", json={'enabled': False})
        self.assertEqual(response.status_code, 200)
        reply = self.ask()
        self.assertEqual(reply['mode'], 'source_unavailable')
        self.assertEqual(reply['knowledge']['evidence'], [])

    def test_changed_official_bytes_cannot_be_replaced_with_reference_notes(self):
        self.source.write_bytes(self.original + '\n변경된 파일'.encode('utf-8'))
        reply = self.ask()
        self.assertEqual(reply['mode'], 'source_unavailable')
        self.assertEqual(reply['knowledge']['evidence'], [])
        self.assertTrue(any(row['reason'] == '원문 변경·미확인' for row in reply['knowledge']['excluded']))

    def test_future_official_version_is_still_excluded(self):
        reply = self.ask(today='2000-01-01')
        self.assertEqual(reply['mode'], 'source_unavailable')
        self.assertEqual(reply['knowledge']['evidence'], [])
        self.assertTrue(any(row['reason'] == '시행일 이전' for row in reply['knowledge']['excluded']))


if __name__ == '__main__':
    unittest.main()
