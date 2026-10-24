import tempfile,unittest,json,io,copy
from pathlib import Path
from datetime import date
from unittest.mock import patch,Mock
from fastapi import HTTPException
from app import folders,knowledge as k,llm

class KnowledgeTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patch=patch.object(folders,'DB_PATH',self.root/'folders.db');self.patch.start();folders.initialize();k.initialize()
        self.docs=self.root/'docs';self.docs.mkdir();self.file=self.docs/'출장 안내.txt';self.file.write_text('업무명: 출장정산\n연도: 2026\n제1조 증빙 서류\n출장정산 신청 시 교통 영수증과 숙박 영수증을 첨부합니다.\n제2조 검토\n담당자는 중복 청구 여부를 확인합니다.',encoding='utf-8')
        self.library=folders.connect(folders.Connect(name='합성 출장 지침',roots=[str(self.docs)]));self.fid=self.library['files'][0]['id']
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def register(self,effective=None):return k.register(self.library['id'],k.Register(version=1,file_ids=[self.fid],kind='기관 지침',institution='합성기관',effective_date=effective))
    def test_opt_in_and_search_scope(self):
        self.assertFalse(k.retrieve('출장 영수증')['hits']);self.register();hits=k.retrieve('출장 영수증',self.library['id'])['hits'];self.assertTrue(hits);self.assertEqual(hits[0]['institution'],'합성기관');self.assertFalse(k.retrieve('출장 영수증','other')['hits'])
    def test_changed_source_excluded(self):
        self.register();self.file.write_text('수정되었습니다',encoding='utf-8');r=k.retrieve('출장 영수증');self.assertFalse(r['hits']);self.assertTrue(r['excluded'])
    def test_future_source_excluded(self):
        self.register(date(2099,1,1));r=k.retrieve('출장 영수증');self.assertFalse(r['hits']);self.assertEqual(r['excluded'][0]['reason'],'시행일 이전')
    def test_disabled_and_repeat_register(self):
        r=self.register();key=r['sources'][0]['id'];self.register();self.assertEqual(len(k.sources()),1);k.enable(key,k.Enable(enabled=False));self.assertFalse(k.retrieve('출장 영수증')['hits'])
    def test_registration_rejects_stale_library_version(self):
        with self.assertRaises(HTTPException) as e:k.register(self.library['id'],k.Register(version=2,file_ids=[self.fid],kind='참고자료'))
        self.assertEqual(e.exception.status_code,409)
    def test_experience_is_separate(self):
        n=k.experience(self.library['id'],k.Experience(title='영수증 누락 경험',author='가상 담당자',situation='출장 영수증이 누락되었습니다.',handling='누락한 영수증을 다시 받았습니다.',caution='중복 청구를 확인합니다.'))
        r=k.retrieve('출장 영수증');self.assertFalse(r['hits']);self.assertEqual(r['experiences'][0]['id'],n['id'])
    def test_quotes_must_exist_and_have_valid_ids(self):
        self.register();hits=k.retrieve('출장 영수증')['hits'];h=hits[0]
        self.assertEqual(k.validate_quotes({'evidence':[{'id':h['id'],'quote':h['text']}]},hits)[0]['quote'],h['text'])
        for item in [{'id':'invented','quote':h['text']},{'id':h['id'],'quote':'등록되지 않은 허위 답변 문장입니다.'},{'id':[],'quote':h['text']}]:self.assertFalse(k.validate_quotes({'evidence':[item]},hits))
    def test_offline_returns_excerpts_without_model(self):
        self.register()
        with patch.object(k.config,'active_profile',return_value={'provider':'offline'}):r=k.answer('출장 영수증',k.retrieve('출장 영수증'))
        self.assertEqual(r['mode'],'source_search');self.assertTrue(r['evidence'])
    def test_model_verified_quotes(self):
        self.register();found=k.retrieve('출장 영수증');h=found['hits'][0]
        with patch.object(k.config,'active_profile',return_value={'provider':'openai_compatible','base_url':'http://127.0.0.1:11434/v1','model':'test'}),patch.object(llm.OpenAICompatibleProvider,'chat',return_value=json.dumps({'evidence':[{'id':h['id'],'quote':h['text']}]})):
            r=k.answer('출장 영수증',found)
        self.assertEqual(r['mode'],'source_llm');self.assertEqual(r['model'],'test')
    def test_model_selects_existing_span_without_retyping_source(self):
        self.register();found=k.retrieve('출장 영수증');choices=k.quote_choices(found['hits']);key=next(iter(choices))
        with patch.object(k.config,'active_profile',return_value={'provider':'openai_compatible','base_url':'http://localhost:11434/v1','model':'test'}),patch.object(llm.OpenAICompatibleProvider,'chat',return_value=json.dumps({'selected_quote_id':key})):
            r=k.answer('출장 영수증',found)
        self.assertEqual(r['mode'],'source_llm')
        self.assertTrue(any(e.get('quote')==choices[key]['source']['text'] for e in r['evidence']))
        self.assertIn(choices[key]['quote'],choices[key]['source']['text'])
    def test_unknown_span_id_falls_back_to_original_source(self):
        self.register();found=k.retrieve('출장 영수증')
        with patch.object(k.config,'active_profile',return_value={'provider':'openai_compatible','base_url':'http://localhost:11434/v1','model':'test'}),patch.object(llm.OpenAICompatibleProvider,'chat',return_value='{"selected_quote_id":"invented"}'):
            r=k.answer('출장 영수증',found)
        self.assertEqual(r['mode'],'source_search');self.assertTrue(r['evidence']);self.assertIn('검증 가능한 인용',r['notice'])
    def test_official_quote_keeps_conditions_and_separate_model_selection(self):
        self.register();found=k.retrieve('출장 영수증');h=found['hits'][0];h['official']={'article':'제1조'}
        short=h['text'][-20:]
        with patch.object(k.config,'active_profile',return_value={'provider':'openai_compatible','base_url':'http://127.0.0.1:11434/v1','model':'test'}),patch.object(llm.OpenAICompatibleProvider,'chat',return_value=json.dumps({'evidence':[{'id':h['id'],'quote':short}]})):
            r=k.answer('출장 영수증',found)
        self.assertEqual(r['evidence'][0]['model_selected_quote'],short)
        self.assertEqual(r['evidence'][0]['quote'],h['text']);self.assertEqual(r['evidence'][0]['quote_basis'],'original_context')

    def test_answer_does_not_mutate_retrieval_or_drop_other_evidence(self):
        self.register();query='출장 영수증';found=k.retrieve(query)
        first=found['hits'][0];first['official']={'article':'제1조'}
        other=copy.deepcopy(first);other.update(id='other:0:0',source_id='other',official=None)
        found['hits'].append(other);before=copy.deepcopy(found)
        choices=k.quote_choices(found['hits'],query);key=next(key for key,item in choices.items() if item['source']['id']==first['id'])
        provider=Mock(available=True);provider.chat.return_value=json.dumps({'selected_quote_id':key})
        with patch.object(k.config,'active_profile',return_value={'base_url':'http://localhost:11434/v1','model':'test'}),patch.object(k.llm,'get_provider',return_value=provider):
            result=k.answer(query,found)
        self.assertEqual(found,before)
        self.assertEqual([e['id'] for e in result['evidence']],[h['id'] for h in found['hits']])
        official=result['evidence'][0]
        self.assertEqual(official['quote'],first['text']);self.assertEqual(official['model_selected_quote'],choices[key]['quote'])
        self.assertEqual(official['quote_basis'],'original_context')

    def test_model_request_caps_timeout_without_changing_profile_and_keeps_fallback_model(self):
        self.register();query='출장 영수증';found=k.retrieve(query)
        profile={'base_url':'http://localhost:11434/v1','model':'test','timeout':120}
        provider=Mock(available=True);provider.chat.return_value='{"selected_quote_id":null}'
        with patch.object(k.config,'active_profile',return_value=profile),patch.object(k.llm,'get_provider',return_value=provider) as get_provider:
            result=k.answer(query,found)
        self.assertEqual(profile['timeout'],120);self.assertEqual(get_provider.call_args.args[0]['timeout'],30)
        self.assertEqual(result['mode'],'source_search');self.assertEqual(result['model'],'test')
        self.assertEqual([e['quote'] for e in result['evidence']],[h['text'] for h in found['hits']])
        messages=provider.chat.call_args.args[0];request=json.loads(messages[1]['content'])
        self.assertEqual(request['question'],query);self.assertTrue(request['quote_options'])
        self.assertEqual(provider.chat.call_args.kwargs,{'max_tokens':80,'temperature':0})

if __name__=='__main__':unittest.main()
