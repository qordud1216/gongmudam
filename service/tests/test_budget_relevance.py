import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

from app import answer_tree, folders, knowledge, knowledge_relevance as relevance, main
from tools.check_question_answers import DEFAULT_MANIFEST


class BudgetQuestionRelevanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_patch = patch.object(folders, 'DB_PATH', Path(cls.tmp.name) / 'folders.db')
        cls.db_patch.start()
        folders.initialize()
        knowledge.initialize()
        lib = folders.connect(folders.Connect(name='예산 질문 검증', roots=[str(DEFAULT_MANIFEST.parent / 'excerpts')]))
        cls.key = lib['id']
        knowledge.register(cls.key, knowledge.Register(version=lib['version'], file_ids=[f['id'] for f in lib['files']], kind='참고자료'))

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.tmp.cleanup()

    def test_budget_wording_is_recognized(self):
        for query in (
            '물품구매하려고 하는데 사무용품은 무슨목으로 사야할까?',
            '사무용품은 어느 목으로 사야 하나요?',
            '사무용품 예산과목이 뭔가요?',
            '사무용품은 어떤 예산으로 사나요?',
            '사무용품은 통계목이 무엇인가요?',
            '사무용품 세목 알려줘',
            '일반운영비에 사무용품을 사도 되나요?',
        ):
            with self.subTest(query=query):
                self.assertTrue(relevance.is_budget_question(query))

    def test_non_budget_questions_are_not_classified_as_budget(self):
        for query in ('물품 납품 검사는 어떻게 하나요?', '출장 정산은 어떻게 하나요?', '목요일에 사무용품 구매'):
            with self.subTest(query=query):
                self.assertFalse(relevance.is_budget_question(query))

    def test_budget_filter_requires_direct_budget_source(self):
        def hit(source_id, title, text):
            return {'source_id': source_id, 'id': source_id, 'title': title, 'text': text,
                    'score': 10, 'official': {'title': title}}

        query = '물품구매하려고 하는데 사무용품은 무슨목으로 사야할까?'
        inspection = hit('inspection', '물품 납품검사 기준', '물품 예산 사용 전 납품검사와 검수 절차')
        payment = hit('payment', '물품 대금 지급', '물품 예산 대금 지급 절차')
        budget = hit('budget', '지방자치단체 예산편성 운영기준 별표 11',
                     '201 일반운영비\n01. 사무관리비\n1. 일반수용비\n기본사무용품비 ... 필기구, 용지대 등 사무용 잡품비')
        selected, _ = relevance.filter_hits(query, [inspection, payment, budget])
        self.assertEqual([h['id'] for h in selected], ['budget'])

    def test_unavailable_budget_answer_does_not_call_model(self):
        found = {'hits': [], 'experiences': [], 'excluded': [], 'unavailable_reason': 'no budget source'}
        with patch.object(knowledge.config, 'active_profile', side_effect=AssertionError('must not inspect model profile')):
            reply = knowledge.answer('사무용품은 무슨 목으로 사야 하나요?', found)
        self.assertEqual(reply['mode'], 'source_unavailable')
        self.assertFalse(reply['evidence'])

    def test_inspection_summary_is_not_used_for_budget_question(self):
        # Reuse the genuine manifest hit configured by the existing fixture.
        with patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}):
            reply = main.api_ask({'query': '물품 검사 후 대금 지급은 어떻게 하나요?', 'knowledge_library_id': self.key, 'today': '2026-10-20'})['knowledge']
        self.assertTrue(reply['evidence'])
        result = answer_tree.build('물품구매 사무용품은 무슨 목으로 사나요?', reply)
        self.assertNotEqual(result.get('rule_id'), 'goods-inspection')
        self.assertNotIn('검수', ' '.join(i['text'] for b in result['branches'] for i in b['items']))

    def ask(self,query,**extra):
        with patch.object(knowledge.config,'active_profile',return_value={'provider':'offline'}):
            return main.api_ask(dict(query=query,knowledge_library_id=self.key,today='2026-10-20',**extra))

    def test_exact_reported_question_uses_budget_table_and_supported_summary(self):
        reply=self.ask('물품구매하려고 하는데 사무용품은 무슨목으로 사야할까?')['knowledge']
        self.assertEqual(reply['tree']['rule_id'],'budget-office-supplies')
        self.assertEqual(len(reply['evidence']),1)
        hit=reply['evidence'][0]
        self.assertEqual(hit['official']['pdf_pages'],[87,88])
        self.assertIn('2026',reply['tree']['note'])
        self.assertIn('국가기관',reply['tree']['note'])
        text=' '.join(i['text'] for b in reply['tree']['branches'] for i in b['items'])
        self.assertIn('201-01',text);self.assertIn('일반수용비',text)
        original=next((DEFAULT_MANIFEST.parent/'excerpts'/r['filename']).read_text(encoding='utf-8')
                      for r in json.loads(DEFAULT_MANIFEST.read_text(encoding='utf-8')) if r['sha256']==hit['sha256'])
        self.assertIn(hit['quote'],original)
        for branch in reply['tree']['branches']:
            for item in branch['items']:
                self.assertEqual(item['ref'],1)
                self.assertTrue(all(q in hit['text'] and q in original for q in item['support_quotes']))

    def test_asset_question_does_not_show_consumable_supplies_summary(self):
        reply=self.ask('지방자치단체 컴퓨터 구매는 무슨 목으로 사야 하나요?')['knowledge']
        self.assertEqual(reply['tree']['rule_id'],'budget-assets')
        self.assertEqual(reply['evidence'][0]['official']['pdf_pages'],[114])

    def test_named_general_operating_budget_does_not_fall_back_to_inspection(self):
        reply=self.ask('일반운영비에 사무용품을 사도 되나요?')['knowledge']
        self.assertEqual(reply['tree']['rule_id'],'budget-office-supplies')
        self.assertTrue(all(h['official'].get('budget_scope') for h in reply['evidence']))

    def test_device_consumables_and_service_costs_are_not_device_acquisition(self):
        for query in ['프린터 토너는 무슨 목으로 사나요?','복사기 잉크는 무슨 목으로 구매하나요?']:
            with self.subTest(query=query):
                reply=self.ask(query)['knowledge']
                self.assertNotEqual(reply['tree'].get('rule_id'),'budget-assets')
                self.assertTrue(all(h['official']['budget_topics']==['office_supplies'] for h in reply['evidence']))
        self.assertEqual(self.ask('프린터 임차료는 무슨 목으로 쓰나요?')['mode'],'source_unavailable')

    def test_no_budget_source_returns_no_basis_instead_of_inspection_or_model(self):
        actual=knowledge.sources(self.key)
        with patch.object(knowledge,'sources',return_value=[s for s in actual if not s.get('official',{}).get('budget_scope')]),\
             patch.object(knowledge.llm,'get_provider',side_effect=AssertionError('no evidence must not call model')):
            result=main.api_ask({'query':'사무용품은 무슨 목으로 사야 할까요?','knowledge_library_id':self.key})
        self.assertEqual(result['mode'],'source_unavailable')
        self.assertEqual(result['knowledge']['tree']['kind'],'unavailable')
        self.assertFalse(result['knowledge']['evidence'])
        self.assertIn('예산 과목',result['knowledge']['tree']['branches'][0]['items'][0]['text'])

    def test_other_accounts_years_and_unregistered_items_are_not_assigned_office_code(self):
        for query in ('국가기관 사무용품은 무슨 목으로 사나요?','교육청 사무용품 예산과목은?',
                      '공기업특별회계 사무용품 예산 목은?', '2027년 사무용품 예산과목은?',
                      '2025년도 사무용품 예산과목은?', '2027 회계연도 사무용품 예산과목은?',
                      '2027 예산 사무용품은 무슨 목으로 사나요?', '교육강사료는 무슨 목으로 집행하나요?',
                      '의료 소모품은 무슨 목으로 사나요?','물품을 사려는데 예산과목은 뭔가요?'):
            with self.subTest(query=query):
                result=self.ask(query)
                self.assertEqual(result['mode'],'source_unavailable')
                self.assertFalse(result['knowledge']['evidence'])


if __name__ == '__main__':
    unittest.main()
