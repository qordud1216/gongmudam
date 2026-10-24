import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app import folders,knowledge as k,knowledge_relevance as rel,main,llm
from tools.check_question_answers import evaluate,load_sources,DEFAULT_MANIFEST

ROOT=Path(__file__).resolve().parents[1]

class QuestionEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db_patch=patch.object(folders,'DB_PATH',Path(self.tmp.name)/'folders.db');self.db_patch.start()
        folders.initialize();k.initialize()
        manifest_rows=json.loads(DEFAULT_MANIFEST.read_text(encoding='utf-8'))
        old_digests={row['sha256'] for row in manifest_rows if row.get('collection') != 'v40'}
        v=folders.connect(folders.Connect(name='공식 조문 검증',roots=[str(DEFAULT_MANIFEST.parent/'excerpts')]))
        self.key=v['id']
        old_files=[f for f in v['files'] if hashlib.sha256(Path(f['path']).read_bytes()).hexdigest() in old_digests]
        k.register(self.key,k.Register(version=v['version'],file_ids=[f['id'] for f in old_files],kind='참고자료'))
    def tearDown(self):self.db_patch.stop();self.tmp.cleanup()
    def test_reviewed_questions_and_exact_quotes_without_model(self):
        sources,errors=load_sources(DEFAULT_MANIFEST);self.assertFalse(errors)
        for case in json.loads((ROOT/'reference_data/question_checks_v34.json').read_text(encoding='utf-8')):
            with self.subTest(case=case['id']),patch.object(k.config,'active_profile',return_value={'provider':'offline'}):
                result=main.api_ask({'query':case['question'],'knowledge_library_id':self.key,'today':'2026-10-20'})
                check=evaluate(case,result,sources);self.assertTrue(check['passed'],check['failures'])
    def test_travel_answer_does_not_include_sick_leave(self):
        hits=k.retrieve('관내출장 4시간 여비 공무용차량',self.key)['hits']
        self.assertTrue(hits)
        self.assertTrue(all(h['official']['title']=='공무원 여비 규정' for h in hits))
    def test_unsupported_question_never_falls_back_to_synthetic_card(self):
        with patch.object(main.assistant,'ask',side_effect=AssertionError('must not use demo card')),patch.object(k.llm,'get_provider',side_effect=AssertionError('must not call model')):
            result=main.api_ask({'query':'출장 위험수당 한도는 얼마인가요?'})
        self.assertEqual(result['mode'],'source_unavailable');self.assertFalse(result['knowledge']['evidence'])
    def test_model_selection_does_not_remove_other_required_source(self):
        found=k.retrieve('물품 검사와 대금 지급은 어떻게 하나요?',self.key);self.assertGreater(len(found['hits']),1)
        h=found['hits'][0]
        provider={'provider':'openai_compatible','base_url':'http://127.0.0.1:11434/v1','model':'test'}
        with patch.object(k.config,'active_profile',return_value=provider),patch.object(llm.OpenAICompatibleProvider,'chat',return_value=json.dumps({'evidence':[{'id':h['id'],'quote':h['text'][:100]}]})):
            reply=k.answer('물품 검사와 대금 지급은 어떻게 하나요?',found)
        self.assertEqual(reply['mode'],'source_llm');self.assertEqual(len(reply['evidence']),len(found['hits']))
    def test_model_timeout_still_returns_verified_sources(self):
        found=k.retrieve('지방공무원 공가 헌혈',self.key)
        with patch.object(k.config,'active_profile',return_value={'provider':'openai_compatible','base_url':'http://127.0.0.1:11434/v1','model':'test'}),patch.object(llm.OpenAICompatibleProvider,'chat',side_effect=llm.LLMError('timeout')):
            reply=k.answer('지방공무원 공가 헌혈',found)
        self.assertEqual(reply['mode'],'source_search');self.assertTrue(reply['notice']);self.assertTrue(reply['evidence'])
    def test_paragraph_and_exception_are_not_cut_at_character_boundary(self):
        paragraph='② '+('조건과 예외를 포함한 긴 원문입니다. '*150)+'다만, 예외를 적용한다.'
        text='제1조 ① 일반 원칙\n'+paragraph+'\n③ 다른 사항'
        windows=rel.legal_windows([{'text':line} for line in text.splitlines()])
        self.assertTrue(any(paragraph in w['text'] for w in windows))
        self.assertTrue(all(w['text'] in text for w in windows))
    def test_missing_annex_is_not_silently_answered(self):
        found=k.retrieve('서울 출장 숙박비 상한액은 얼마인가요?',self.key)
        self.assertFalse(found['hits']);self.assertIn('별표 2',found['unavailable_reason'])
    def test_settlement_speed_question_is_not_a_monetary_rate_question(self):
        found=k.retrieve('출장 후 숙박비 정산은 얼마나 빨리 신청해야 하나요?',self.key)
        self.assertTrue(found['hits']);self.assertTrue(any(h['official']['article'].startswith('제8조의2') for h in found['hits']))
    def test_education_collection_question_does_not_cite_travel_law(self):
        query='교육 참석 희망자 취합 근거 규정은?'
        found=k.retrieve(query,self.key)
        self.assertFalse(found['hits'])
        with patch.object(k.llm,'get_provider',side_effect=AssertionError('unrelated model citation')):
            result=main.api_ask({'query':query,'knowledge_library_id':self.key,'today':'2026-10-20'})
        self.assertEqual(result['mode'],'source_unavailable')
        self.assertEqual(result['task_action']['kind'],'education_collection')

if __name__=='__main__':unittest.main()
