import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import answer_tree as tree, folders, knowledge, main
from tools.check_question_answers import DEFAULT_MANIFEST

ROOT = Path(__file__).resolve().parents[1]


class AnswerTreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_patch = patch.object(folders, 'DB_PATH', Path(cls.tmp.name) / 'folders.db')
        cls.db_patch.start()
        folders.initialize()
        knowledge.initialize()
        lib = folders.connect(folders.Connect(name='요약 검증', roots=[str(DEFAULT_MANIFEST.parent / 'excerpts')]))
        cls.key = lib['id']
        knowledge.register(cls.key, knowledge.Register(version=lib['version'], file_ids=[f['id'] for f in lib['files']], kind='참고자료'))

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.tmp.cleanup()

    def ask(self, question):
        with patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}):
            return main.api_ask({'query': question, 'knowledge_library_id': self.key, 'today': '2026-10-20'})['knowledge']

    def test_reviewed_questions_keep_exact_support_and_reference(self):
        cases = json.loads((ROOT / 'reference_data/question_checks_v34.json').read_text(encoding='utf-8'))
        for case in cases:
            with self.subTest(case=case['id']):
                reply = self.ask(case['question'])
                result = reply['tree']
                if reply['evidence']:
                    self.assertEqual(result['kind'], 'summary')
                    for branch in result['branches']:
                        for item in branch['items']:
                            hit = reply['evidence'][item['ref'] - 1]
                            reviewed_digests = result.get('reviewed_source_sha256s', [result.get('reviewed_source_sha256')])
                            self.assertIn(hit['sha256'], reviewed_digests)
                            self.assertTrue(all(q in hit['text'] for q in item['support_quotes']))
                else:
                    self.assertEqual(result['kind'], 'unavailable')
                    self.assertTrue(all(i['ref'] is None for b in result['branches'] for i in b['items']))

    def test_changed_source_digest_does_not_receive_reviewed_summary(self):
        reply = self.ask('물품 검사 후 대금 지급은 어떻게 하나요?')
        for hit in reply['evidence']:
            hit['sha256'] = '0' * 64
        self.assertEqual(tree.build('물품 대금 지급', reply)['kind'], 'extract')

    def test_missing_exception_quote_does_not_leave_only_general_principle(self):
        reply = self.ask('물품 검사 후 대금 지급은 어떻게 하나요?')
        hit = next(h for h in reply['evidence'] if '선금급(先金給)' in h['text'])
        reply = {'evidence': [copy.deepcopy(hit)]}
        reply['evidence'][0]['text'] = hit['text'].replace('선금급(先金給)', '')
        self.assertEqual(tree.build('물품 대금 지급', reply)['kind'], 'extract')

    def test_additional_expenses_never_receive_general_two_week_deadline(self):
        for area in ('국내', '국외'):
            with self.subTest(area=area):
                reply = self.ask(f'국가공무원 {area} 출장 부득이한 사유로 숙박비를 초과지출해 추가로 정산받을 때 신청기한은?')
                self.assertNotEqual(reply['tree'].get('rule_id'), 'settlement')
                if reply['tree']['kind'] == 'summary':
                    self.assertEqual(reply['tree']['rule_id'], 'additional-settlement')
                    text = ' '.join(i['text'] for b in reply['tree']['branches'] for i in b['items'])
                    self.assertIn('국내는 출장 다음 날부터 1주', text)
                    self.assertIn('국외는 출장 다음 날부터 2주', text)

    def test_card_purchase_exception_retains_scope(self):
        result = self.ask('지방자치단체 신용카드 포인트를 세입조치할 수 없으면 물품 구매에 써도 되나요?')['tree']
        self.assertEqual(result['rule_id'], 'card-points')
        exception = result['branches'][1]['items'][0]
        self.assertIn('위 경우 외에 대형할인점·문구점', exception['text'])
        self.assertTrue(any('제1항 외에' in q for q in exception['support_quotes']))

    def test_word_additional_does_not_override_daily_allowance_question(self):
        result = self.ask('국가공무원 출장 일비 공용차량 이용하면 추가 감액이 되나요?')['tree']
        self.assertEqual(result.get('rule_id'), 'daily-car')


if __name__ == '__main__':
    unittest.main()
