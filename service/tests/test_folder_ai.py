import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import config,folder_ai,folders,llm

class FolderAITest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'자료';self.source.mkdir()
  (self.source/'메모.txt').write_text('오는 2026년 11월 6일 어르신 스마트폰 수업을 준비합니다.\n참석자 회신이 아직 취합되지 않아 명단 확인이 필요합니다.',encoding='utf-8')
  self.dbpatch=patch.object(folders,'DB_PATH',self.root/'folders.db');self.dbpatch.start();folders.initialize();folder_ai.initialize()
  self.cfg={'llm':{'active':'offline','profiles':{'gemma':{'provider':'openai_compatible','base_url':'http://127.0.0.1:18080/v1','model':'unit-gemma','api_key':'unit-private-secret','timeout':1},'llama':{'provider':'openai_compatible','base_url':'http://127.0.0.1:18080/v1','model':'unit-llama'},'external':{'provider':'openai_compatible','base_url':'https://external.invalid/v1','model':'remote'},'offline':{'provider':'offline'}}}}
  self.cfgpatch=patch.object(config,'load',return_value=self.cfg);self.cfgpatch.start();app=FastAPI();app.include_router(folders.router);app.include_router(folder_ai.router);self.client=TestClient(app)
  self.v=self.req('POST','/libraries',{'name':'합성 AI 자료함','roots':[str(self.source)]},201);self.key=self.v['id'];self.fid=self.v['files'][0]['id'];self.prefix=f'/libraries/{self.key}'
 def tearDown(self):self.client.close();self.cfgpatch.stop();self.dbpatch.stop();self.temp.cleanup()
 def req(self,method,path,body=None,status=200):
  r=self.client.request(method,'/api/folders'+path,json=body);self.assertEqual(r.status_code,status,r.text);return r.json()
 def output(self):
  e={'file_id':self.fid,'unit':1,'quote':'어르신 스마트폰 수업을 준비합니다.'}
  return {'new_projects':[{'key':'n1','name':'어르신 스마트폰 수업 준비'}],'assignments':[{'file_id':self.fid,'project':'new:n1','reason':'어르신 대상 수업 준비와 관련된 회신','evidence':[e]}],
          'projects':[{'project':'new:n1','summary':{'text':'어르신 스마트폰 수업 준비 자료입니다.','evidence':[copy.deepcopy(e)]},'actions':[{'text':'참석 희망자 명단 취합 여부를 확인하세요.','evidence':[{'file_id':self.fid,'unit':2,'quote':'참석자 회신이 아직 취합되지 않아 명단 확인이 필요합니다.'}]}]}]}
 def begin(self,output=None,profile='gemma',version=None):
  payload={'model':'unit-gemma' if profile=='gemma' else 'unit-llama','choices':[{'message':{'content':json.dumps(output if output is not None else self.output(),ensure_ascii=False)}}]}
  with patch.object(llm.httpx,'post',return_value=httpx.Response(200,json=payload)) as call:
   start=self.req('POST',self.prefix+'/ai-runs',dict(version=version or self.v['version'],profile=profile),202)
  result=self.req('GET',self.prefix+'/ai-runs/'+start['id']);return result,call
 def apply(self,r,**kw):return self.req('POST',self.prefix+'/ai-runs/'+r['id']+'/apply',dict(version=self.v['version'],file_ids=[self.fid],apply_notes=True)|kw)
 def test_real_adapter_json_request_loopback_and_no_global_model_change(self):
  r,call=self.begin();self.assertEqual(r['status'],'completed');self.assertTrue(r['actual_response']);self.assertEqual(self.cfg['llm']['active'],'offline')
  args=call.call_args;self.assertEqual(args.args[0],'http://127.0.0.1:18080/v1/chat/completions');self.assertEqual(args.kwargs['json']['model'],'unit-gemma');self.assertEqual(args.kwargs['json']['response_format'],{'type':'json_object'})
  self.assertNotIn('unit-private-secret',json.dumps(r));self.assertNotIn('response_text',r)
 def test_options_exclude_remote_and_offline_and_keys(self):
  v=self.req('GET','/ai-options');self.assertEqual({p['id'] for p in v['profiles']},{'gemma','llama'});self.assertNotIn('secret',json.dumps(v))
 def test_remote_profile_rejected_without_network_call(self):
  with patch.object(llm.httpx,'post') as call:self.req('POST',self.prefix+'/ai-runs',dict(version=1,profile='external'),422);call.assert_not_called()
 def test_llama_profile_selected_for_this_call(self):
  r,call=self.begin(profile='llama');self.assertEqual(r['model'],'unit-llama');self.assertEqual(call.call_args.kwargs['json']['model'],'unit-llama')
 def test_proposal_does_not_change_library_before_apply(self):
  r,_=self.begin();v=self.req('GET',self.prefix);self.assertEqual(v['version'],1);self.assertFalse(v['projects']);self.assertFalse(v['files'][0]['project_ids'])
  v=self.apply(r);self.assertEqual(v['version'],2);self.assertEqual(len(v['projects']),1);self.assertEqual(v['files'][0]['project_ids'],[v['projects'][0]['id']]);self.assertEqual(v['projects'][0]['ai_note']['summary']['evidence'][0]['loc'],'1행')
 def test_quotes_are_matched_against_actual_sent_units(self):
  out=self.output();out['assignments'][0]['evidence'][0]['quote']='없는 근거를 지어낸 모델 답변입니다.'
  r,_=self.begin(out);self.assertEqual(r['status'],'failed');self.assertIn('근거',r['error']);self.assertEqual(self.req('GET',self.prefix)['version'],1)
 def test_out_of_scope_file_or_duplicate_assignments_fail(self):
  for change in ('unknown','duplicate'):
   out=self.output()
   if change=='unknown':out['assignments'][0]['file_id']='unknown'
   else:out['assignments'].append(copy.deepcopy(out['assignments'][0]))
   r,_=self.begin(out);self.assertEqual(r['status'],'failed')
 def test_invalid_target_rejected(self):
  out=self.output();out['assignments'][0]['project']='unknown';r,_=self.begin(out);self.assertEqual(r['status'],'failed')
 def test_invalid_notes_rejected_without_discarding_valid_assignment(self):
  out=self.output();out['projects'][0]['summary']['evidence'][0]['quote']='본문에 없는 요약 인용입니다.';r,_=self.begin(out)
  self.assertEqual(r['status'],'completed');self.assertFalse(r['result']['projects']);self.assertTrue(r['result']['issues']);self.assertEqual(len(self.apply(r)['projects']),1)
 def test_changed_version_blocks_stale_apply_atomically(self):
  r,_=self.begin();v=self.req('POST',self.prefix+'/projects',dict(version=1,name='사용자 업무'),201)
  self.req('POST',self.prefix+'/ai-runs/'+r['id']+'/apply',dict(version=v['version'],file_ids=[self.fid]),409)
  self.assertTrue(self.req('GET',self.prefix+'/ai-runs/'+r['id'])['stale']);self.assertEqual(len(self.req('GET',self.prefix)['projects']),1)
 def test_user_classification_protected_even_if_model_suggests_other_project(self):
  v=self.req('POST',self.prefix+'/projects',dict(version=1,name='사용자 확정 업무'),201);pid=v['projects'][0]['id']
  v=self.req('PATCH',self.prefix+'/files/'+self.fid,dict(version=v['version'],project_ids=[pid],reason='담당자가 기존 업무로 확인'))
  r,_=self.begin(version=v['version']);self.assertTrue(r['result']['assignments'][0]['protected'])
  self.req('POST',self.prefix+'/ai-runs/'+r['id']+'/apply',dict(version=v['version'],file_ids=[self.fid],apply_notes=False),422)
  self.assertEqual(self.req('GET',self.prefix)['files'][0]['project_ids'],[pid])
 def test_timeout_does_not_return_a_fake_ai_result(self):
  with patch.object(llm.httpx,'post',side_effect=httpx.ConnectError('unit-only')):
   r=self.req('POST',self.prefix+'/ai-runs',dict(version=1,profile='gemma'),202)
  v=self.req('GET',self.prefix+'/ai-runs/'+r['id']);self.assertEqual(v['status'],'failed');self.assertNotIn('result',v);self.assertEqual(self.req('GET',self.prefix)['version'],1)
 def test_json_failure_and_unknown_fields_rejected(self):
  out=self.output();out['unexpected']='discard';r,_=self.begin(out);self.assertEqual(r['status'],'failed')
 def test_apply_idempotence_prevents_duplicate_projects(self):
  r,_=self.begin();self.apply(r);self.req('POST',self.prefix+'/ai-runs/'+r['id']+'/apply',dict(version=2,file_ids=[self.fid]),409);self.assertEqual(len(self.req('GET',self.prefix)['projects']),1)
 def test_rescan_marks_saved_summary_stale_when_evidence_changes(self):
  r,_=self.begin();v=self.apply(r);self.assertFalse(v['projects'][0]['ai_note']['stale'])
  (self.source/'메모.txt').write_text('변경된 업무 자료 내용입니다.',encoding='utf-8');v=self.req('POST',self.prefix+'/scan',dict(version=2));self.assertTrue(v['projects'][0]['ai_note']['stale']);self.assertTrue(v['files'][0]['manual'])
 def test_explicit_partial_read_and_document_limit(self):
  for n in range(15):(self.source/f'{n}.txt').write_text(('어르신 교육 준비 내용입니다.\n'*30),encoding='utf-8')
  self.v=self.req('POST',self.prefix+'/scan',dict(version=1));r,_=self.begin();self.assertEqual(r['input']['selected_files'],12);self.assertEqual(r['input']['eligible_files'],16);self.assertTrue(any(d['partial'] for d in r['input']['documents']))
 def test_restart_marks_unfinished_run_interrupted(self):
  with folders.db() as c:c.execute('INSERT INTO folder_ai_runs VALUES(?,?,?,?)',('pending',self.key,'running',json.dumps({'id':'pending','status':'running'})))
  folder_ai.initialize()
  with folders.db() as c:self.assertEqual(c.execute('SELECT status FROM folder_ai_runs WHERE id=?',('pending',)).fetchone()[0],'interrupted')
 def test_single_active_run_and_version_guard(self):
  with folders.db() as c:c.execute('INSERT INTO folder_ai_runs VALUES(?,?,?,?)',('pending',self.key,'running',json.dumps({'id':'pending','status':'running'})))
  self.req('POST',self.prefix+'/ai-runs',dict(version=1,profile='gemma'),409)
 def test_unknown_selected_file_rejected(self):self.req('POST',self.prefix+'/ai-runs',dict(version=1,profile='gemma',file_ids=['unknown']),422)

 def test_compact_ids_are_expanded_and_citations_keep_actual_file_id(self):
  out=self.output();out['assignments'][0]['file_id']='d1'
  for a in out['assignments']:
   for e in a['evidence']:e['file_id']='d1'
  for p in out['projects']:
   for claim in [p['summary'],*p['actions']]:
    for e in claim['evidence']:e['file_id']='d1'
  r,_=self.begin(out);self.assertEqual(r['status'],'completed');self.assertEqual(r['result']['assignments'][0]['evidence'][0]['file_id'],self.fid)
 def test_ollama_native_schema_context_is_per_request(self):
  response=httpx.Response(200,json={'model':'gemma3:4b','message':{'content':json.dumps(self.output())},'done':True,'done_reason':'stop','eval_count':123})
  with patch.object(folder_ai.httpx,'post',return_value=response) as call:
   content,meta=folder_ai.call_model({'base_url':'http://127.0.0.1:11434/v1','model':'gemma3:4b'},[{'role':'user','content':'unit'}])
  self.assertEqual(call.call_args.args[0],'http://127.0.0.1:11434/api/chat');self.assertIn('$defs',call.call_args.kwargs['json']['format']);self.assertEqual(call.call_args.kwargs['json']['options']['num_ctx'],16384);self.assertTrue(meta['actual_response']);self.assertEqual(meta['usage']['eval_count'],123)
 def test_native_bad_http_and_unfinished_response_rejected(self):
  for response in [httpx.Response(500,text='private-server-detail'),httpx.Response(200,json={'done':False,'message':{'content':'partial'}})]:
   with patch.object(folder_ai.httpx,'post',return_value=response):
    with self.assertRaises(llm.LLMError) as caught:folder_ai.call_model({'base_url':'http://127.0.0.1:11434/v1','model':'gemma3:4b'},[])
    self.assertNotIn('private-server-detail',str(caught.exception))
 def test_snapshot_evidence_cannot_quote_unsent_tail(self):
  with folders.db() as c:v=folders.get(c,self.key)
  v['files'][self.fid]['units']=[{'text':'가'*800+'전송하지 않은 뒷부분 문장입니다.','loc':'1행'}]
  data=folder_ai.make_input(v,folder_ai.Start(version=1,profile='gemma'));out=self.output();out['assignments'][0]['evidence'][0]['quote']='전송하지 않은 뒷부분 문장입니다.'
  result=folder_ai.validate_output(json.dumps(out),data,v);self.assertFalse(result['assignments'])

 def test_disk_change_without_rescan_blocks_start_and_apply(self):
  r,_=self.begin();(self.source/'메모.txt').write_text('원본이 바뀐 업무 자료입니다.',encoding='utf-8')
  self.req('POST',self.prefix+'/ai-runs',dict(version=1,profile='gemma'),409)
  self.req('POST',self.prefix+'/ai-runs/'+r['id']+'/apply',dict(version=1,file_ids=[self.fid]),409)
  self.assertEqual(self.req('GET',self.prefix)['version'],1)
 def test_report_preserves_scope_model_and_evidence_without_keys(self):
  r,_=self.begin();response=self.client.get('/api/folders'+self.prefix+'/ai-runs/'+r['id']+'/report.json');self.assertEqual(response.status_code,200);self.assertEqual(response.json()['response_model'],'unit-gemma');self.assertNotIn('unit-private-secret',response.text)

 def test_schema_dictionary_output_maps_document_keys_to_real_ids(self):
  with folders.db() as c:v=folders.get(c,self.key)
  data=folder_ai.make_input(v,folder_ai.Start(version=1,profile='gemma'));prompt,aliases=folder_ai.compact_input(data);schema=folder_ai.model_schema(prompt)
  self.assertEqual(schema['properties']['assignments']['required'],['d1'])
  self.assertEqual(schema['properties']['new_projects']['maxItems'],1)
  self.assertEqual(schema['properties']['projects']['maxItems'],1)
  self.assertEqual(schema['$defs']['NewProject']['properties']['key']['enum'],['n1'])
  out=self.output();a=out['assignments'][0];a.pop('file_id');out['assignments']={'d1':a}
  result=folder_ai.validate_output(json.dumps(out),data,v,aliases);self.assertEqual(result['assignments'][0]['file_id'],self.fid)
 def test_missing_new_project_definition_gets_one_model_repair_without_auto_apply(self):
  invalid=self.output();invalid['new_projects']=[]
  def response(value):return httpx.Response(200,json={'model':'unit-gemma','choices':[{'message':{'content':json.dumps(value,ensure_ascii=False)}}]})
  with patch.object(llm.httpx,'post',side_effect=[response(invalid),response(self.output())]) as call:
   start=self.req('POST',self.prefix+'/ai-runs',dict(version=1,profile='gemma'),202)
  run=self.req('GET',self.prefix+'/ai-runs/'+start['id'])
  self.assertEqual(call.call_count,2);self.assertEqual(run['status'],'completed');self.assertEqual(run['generation_attempts'],2)
  self.assertEqual(self.req('GET',self.prefix)['version'],1)
  self.assertNotIn('model_attempts',run)
  with folders.db() as c:stored=folder_ai.stored(c,self.key,start['id'])
  self.assertEqual(len(stored['model_attempts']),2)
  feedback=call.call_args.kwargs['json']['messages'][-1]['content'];self.assertIn('new:n1',feedback)
 def test_repair_is_bounded_and_still_rejects_invalid_project_definitions(self):
  invalid=self.output();invalid['new_projects']=[]
  r,call=self.begin(invalid)
  self.assertEqual(call.call_count,2);self.assertEqual(r['status'],'failed')
  self.assertEqual(self.req('GET',self.prefix)['version'],1)

 def test_inferred_narrative_event_date_blocks_wrong_existing_project(self):
  (self.source/'행사계획.txt').write_text('행사명: 안전체험\n연도: 2026\n개최일: 2026-10-30',encoding='utf-8');self.v=self.req('POST',self.prefix+'/scan',dict(version=1));pid=self.v['projects'][0]['id']
  out=self.output();out['assignments'][0]['project']=pid;r,_=self.begin(out);self.assertEqual(r['status'],'failed');self.assertFalse(self.req('GET',self.prefix)['files'][0].get('ai_assignment'))
 def test_conflicting_dates_cannot_form_one_new_ai_group(self):
  (self.source/'재고.txt').write_text('2026년 12월 10일 비품 재고 점검을 준비합니다.',encoding='utf-8');self.v=self.req('POST',self.prefix+'/scan',dict(version=1));fid=next(f['id'] for f in self.v['files'] if f['name']=='재고.txt')
  out=self.output();out['new_projects'][0]['name']='수업·점검 준비';out['assignments'].append({'file_id':fid,'project':'new:n1','reason':'같은 업무로 잘못 연결한 모의 응답','evidence':[{'file_id':fid,'unit':1,'quote':'2026년 12월 10일 비품 재고 점검을 준비합니다.'}]})
  r,_=self.begin(out);self.assertEqual(r['status'],'failed');self.assertFalse(self.req('GET',self.prefix)['projects'])
 def test_boilerplate_label_is_not_substantive_evidence(self):
  with folders.db() as c:v=folders.get(c,self.key)
  v['files'][self.fid]['units']=[{'text':'[합성 검증 자료]','loc':'1행'}];data=folder_ai.make_input(v,folder_ai.Start(version=1,profile='gemma'));out=self.output();out['assignments'][0]['evidence'][0]['quote']='[합성 검증 자료]'
  result=folder_ai.validate_output(json.dumps(out),data,v);self.assertFalse(result['assignments'])

 def test_new_project_name_from_unrelated_document_rejected(self):
  out=self.output();out['new_projects'][0]['name']='연말 비품 재고 점검';r,_=self.begin(out);self.assertEqual(r['status'],'failed')

 def test_accepted_quote_contributes_stage_evidence_without_completion_claim(self):
  out=self.output();out['assignments'][0]['evidence']=[{'file_id':self.fid,'unit':2,'quote':'참석자 회신이 아직 취합되지 않아 명단 확인이 필요합니다.'}]
  r,_=self.begin(out);v=self.apply(r);p=v['projects'][0];self.assertEqual(p['stages'][1]['files'],[self.fid]);self.assertIn('실제 처리 여부',p['next_actions'][0])

if __name__=='__main__':unittest.main()
