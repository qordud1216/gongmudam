"""Conversation-first preparation with deterministic evidence and optional AI."""
from unittest.mock import patch
from test_core import Base
from app import guidance, knowledge, main, llm


class GuidanceTest(Base):
    def setUp(self):
        self.hit=dict(id='law-unit',source_id='law',title='검증용 여비 규정',sha256='a'*64,text='증빙을 확인하고 정산을 신청한다.',loc='제1조',official=None)
        self.found=dict(hits=[self.hit],experiences=[],excluded=[],intent=None,requires_basis=True)
        self.manual=dict(knowledge=dict(evidence=[dict(id='manual:page:7',source_id='manual',reference_kind='system_manual',title='출장관리',sha256='b'*64,loc='PDF 7쪽',page=7,quote='정산내역을 선택합니다.')],scope='사용법',notice=''))

    def run_guide(self,query='출장 정산을 도와줘',**body):
        with patch.object(knowledge,'retrieve',return_value=self.found),patch.object(guidance.manual_knowledge,'respond',return_value=self.manual):
            return main.api_ask(dict(query=query,guidance=True,today='2026-10-24',**body))

    def test_default_never_constructs_provider_and_combines_manual_and_law(self):
        with patch.object(llm,'get_provider',side_effect=AssertionError('default must not use a model')):
            result=self.run_guide()
        self.assertEqual(result['mode'],'structured_guidance')
        self.assertFalse(result['guidance']['ai_used'])
        self.assertEqual(result['knowledge']['evidence'][0]['quote'],self.hit['text'])
        self.assertEqual(result['guidance']['manual']['evidence'][0]['page'],7)
        self.assertTrue(result['guidance']['steps'])
        self.assertEqual(result['guidance']['deadlines'],[]) # no invented deadline

    def test_ai_opt_in_selects_validated_original_only(self):
        provider=llm.BaseProvider({})
        with patch.object(llm,'get_provider',return_value=provider),patch.object(provider,'chat',return_value='{"selected_quote_id":"q1"}') as call,patch.object(knowledge.config,'active_profile',return_value=dict(base_url='http://127.0.0.1:11434/v1',model='test-model')):
            result=self.run_guide(use_ai=True)
        call.assert_called_once();self.assertTrue(result['guidance']['ai_used'])
        self.assertEqual(result['knowledge']['evidence'][0]['quote'],self.hit['text'])

    def test_bad_ai_quote_does_not_become_evidence(self):
        provider=llm.BaseProvider({})
        with patch.object(llm,'get_provider',return_value=provider),patch.object(provider,'chat',return_value='{"selected_quote_id":"invented"}'),patch.object(knowledge.config,'active_profile',return_value=dict(base_url='http://127.0.0.1:11434/v1',model='test-model')):
            result=self.run_guide(use_ai=True)
        self.assertFalse(result['guidance']['ai_used']);self.assertNotIn('invented',result['answer'])

    def test_context_followup_uses_latest_topic_and_does_not_rewrite_explicit_topic(self):
        context='부산으로 출장다녀왔어\n물품 구매 예산 목이 뭐야?'
        self.assertNotIn('부산',guidance.effective_query('서식도 알려줘',context))
        self.assertEqual(guidance.effective_query('공가를 쓰려면?',context),'공가를 쓰려면?')
        self.assertIn('광주',guidance.effective_query('정산 도와줘','광주로 2박 3일 출장다녀왔어'))
        self.assertEqual(guidance.effective_query('정산 도와줘','가'*3001),'정산 도와줘')

    def test_manual_usage_is_not_legal_authority(self):
        with patch.object(knowledge,'retrieve',side_effect=AssertionError('manual-only must not query unrelated law')),patch.object(guidance.manual_knowledge,'respond',return_value=self.manual):
            result=main.api_ask(dict(query='e-사람 출장 정산 내역 불러오는 방법',guidance=True))
        self.assertEqual(result['knowledge']['evidence'],[])
        self.assertEqual(result['guidance']['manual']['evidence'][0]['reference_kind'],'system_manual')

    def test_situation_with_system_usage_keeps_both_legal_and_manual_evidence(self):
        result=self.run_guide('국가공무원인데 광주로 2박 3일 출장다녀왔어. 정산 방법과 e-사람 사용법을 알려줘')
        self.assertTrue(result['knowledge']['evidence']);self.assertTrue(result['guidance']['manual']['evidence'])

    def test_budget_question_does_not_offer_an_unrelated_inspection_form(self):
        self.assertEqual(self.run_guide('사무용품 예산 목은?')['guidance']['forms'],[])

    def test_leave_companion_keeps_specific_leave_reason(self):
        with patch.object(knowledge,'retrieve',return_value=self.found),patch.object(guidance.manual_knowledge,'respond',return_value=self.manual) as manual:
            main.api_ask(dict(query='국가공무원 배우자 출산휴가는 며칠이야?',guidance=True))
        self.assertIn('출산휴가',manual.call_args.args[0])

    def test_missing_sources_still_guides_without_making_up_answers(self):
        self.found.update(hits=[],requires_basis=False)
        with patch.object(llm,'get_provider',side_effect=AssertionError('no provider')):
            result=self.run_guide('등록 안 된 수당의 지급액이 얼마야?')
        self.assertEqual(result['knowledge']['evidence'],[])
        self.assertFalse(result['guidance']['deadlines'])
        self.assertTrue(result['guidance']['questions'])

    def test_unknown_pay_question_does_not_use_weak_unrelated_matches(self):
        with patch.object(knowledge,'retrieve',side_effect=AssertionError('unknown topic must not use weak matches')):
            result=main.api_ask(dict(query='등록되지 않은 수당 지급액을 알려줘',guidance=True))
        self.assertEqual(result['knowledge']['evidence'],[])
        self.assertNotIn('출장',guidance.effective_query('등록 안 된 수당 기한을 알려줘','출장 다녀왔어'))

    def test_data_map_provenance_and_no_dangling_edges(self):
        result=self.run_guide();m=result['guidance']['map'];ids={n['id'] for n in m['nodes']}
        self.assertTrue(all(e['source'] in ids and e['target'] in ids for e in m['edges']))
        self.assertTrue(any(n.get('sha256')=='a'*64 for n in m['nodes']))
        self.assertTrue(any(n.get('page')==7 for n in m['nodes']))
        self.assertNotIn('path',str(m))

    def test_selected_library_is_respected_for_both_searches(self):
        with patch.object(knowledge,'retrieve',return_value=self.found) as legal,patch.object(guidance.manual_knowledge,'respond',return_value=self.manual) as manual:
            main.api_ask(dict(query='출장 정산 도와줘',guidance=True,knowledge_library_id='selected'))
        self.assertEqual(legal.call_args.args[1],'selected');self.assertEqual(manual.call_args.args[1],'selected')
