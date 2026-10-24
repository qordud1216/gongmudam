import copy,json,unittest
from unittest.mock import patch
import httpx
from app import folders,folder_ai,folder_watch,change_inbox,llm
from tests import test_folder_ai as ai_tests

class ChangeInboxTest(unittest.TestCase):
 setUp=ai_tests.FolderAITest.setUp
 tearDown=ai_tests.FolderAITest.tearDown
 req=ai_tests.FolderAITest.req
 def prepare(self):
  self.client.app.include_router(change_inbox.router);self.client.app.include_router(folder_watch.router);folder_watch.initialize()
  (self.source/'비품.txt').write_text('부서 비품의 컴퓨터와 책상 실물 수량을 조사합니다.\n미회신 부서의 비품 목록 확인이 필요합니다.',encoding='utf-8')
  self.v=self.req('POST',self.prefix+'/scan',{'version':1})
  for name in ('스마트폰 교육','부서 비품 조사'):self.v=self.req('POST',self.prefix+'/projects',dict(version=self.v['version'],name=name),201)
  self.p1=next(p['id'] for p in self.v['projects'] if p['name']=='스마트폰 교육');self.p2=next(p['id'] for p in self.v['projects'] if p['name']=='부서 비품 조사')
  self.f2=next(f['id'] for f in self.v['files'] if f['id']!=self.fid)
  self.out={'new_projects':[],'assignments':[],'projects':[]}
  for fid,pid,text,quote,action in [(self.fid,self.p1,'어르신 스마트폰 수업을 준비하며 참석자 명단 회신 취합과 좌석 배치 확인이 필요한 자료입니다.','어르신 스마트폰 수업을 준비합니다.','참석자 명단 회신을 확인하세요.'),(self.f2,self.p2,'부서 비품의 컴퓨터와 책상 실물 수량을 조사하며 미회신 부서 자료의 추가 확인이 필요한 자료입니다.','컴퓨터와 책상 실물 수량을 조사합니다.','미회신 부서의 비품 목록을 확인하세요.')]:
   e={'file_id':fid,'unit':1,'quote':quote};self.out['assignments'].append(dict(file_id=fid,project=pid,reason='원문 내용에 따라 관련 업무로 제안',evidence=[copy.deepcopy(e)]));self.out['projects'].append(dict(project=pid,summary=dict(text=text,evidence=[copy.deepcopy(e)]),actions=[dict(text=action,evidence=[copy.deepcopy(e)])]))
  self.run=self.start(self.out);self.rid=self.run['id']
 def start(self,out):
  payload={'choices':[{'message':{'content':json.dumps(out,ensure_ascii=False)}}]}
  with patch.object(llm.httpx,'post',return_value=httpx.Response(200,json=payload)):
   r=self.req('POST',self.prefix+'/ai-runs',dict(version=self.v['version'],profile='gemma'),202)
  r=self.req('GET',self.prefix+'/ai-runs/'+r['id']);self.assertEqual(r['status'],'completed',r);return r
 def list(self,query=''):return self.req('GET','/change-inbox'+query)
 def raw(self):
  with folders.db() as c:return folders.get(c,self.key)
 def detail(self,target):return self.req('GET',f'/change-inbox/{self.key}/{self.rid}?target={target}')
 def decide(self,target,action,revision=None,version=None,status=200,**extra):
  d=self.detail(target)
  return self.req('POST',f'/change-inbox/{self.key}/{self.rid}/review',dict(target=target,action=action,revision=d['revision'] if revision is None else revision,version=d['library_version'] if version is None else version)|extra,status)
 def test_separate_cards_per_work_and_detail_evidence(self):
  self.prepare();v=self.list();self.assertEqual(v['total'],2);self.assertEqual(v['counts']['pending'],2)
  d=self.detail(self.p1);self.assertEqual(len(d['assignments']),1);self.assertEqual(d['assignments'][0]['file_id'],self.fid);self.assertTrue(d['proposed_note']['summary']['evidence']);self.assertTrue(d['previous_state_available']);self.assertNotIn('unit-private-secret',json.dumps(d))
 def test_only_selected_work_applies_remaining_work_stays_fresh(self):
  self.prepare();old=self.raw();r=self.decide(self.p1,'apply');v=self.raw();self.assertEqual(v['files'][self.fid]['project_ids'],[self.p1]);self.assertEqual(v['files'][self.f2]['project_ids'],[]);self.assertNotIn('ai_note',v['projects'][self.p2]);self.assertEqual(v['version'],old['version']+1);self.assertEqual(self.detail(self.p1)['history'][-1]['file_ids'],[self.fid])
  d=self.detail(self.p2);self.assertFalse(d['stale']);self.assertEqual(d['status'],'pending');self.decide(self.p2,'apply');self.assertEqual(self.list()['total'],0);self.assertEqual(self.list('?status=applied')['total'],2)
 def test_seen_defer_reopen_do_not_write_library(self):
  self.prepare();old=self.raw();self.decide(self.p1,'seen');self.assertEqual(self.detail(self.p1)['status'],'reviewing');self.decide(self.p1,'defer');self.assertEqual(self.detail(self.p1)['status'],'deferred');self.assertEqual(self.raw(),old);self.decide(self.p1,'reopen');self.assertEqual(self.detail(self.p1)['status'],'reviewing');self.assertEqual(len(self.detail(self.p1)['history']),3)
 def test_all_deferred_completes_queue_review_without_fake_apply(self):
  self.prepare();self.decide(self.p1,'defer');r=self.decide(self.p2,'defer');self.assertTrue(r['review_complete']);self.assertEqual(self.list()['total'],0)
  run=self.req('GET',self.prefix+'/ai-runs/'+self.rid);self.assertFalse(run['applied']);self.assertEqual(len(run['reviews']),2)
 def test_other_work_file_injection_rejected_atomically(self):
  self.prepare();old=self.raw();self.decide(self.p1,'apply',file_ids=[self.f2],status=422);self.assertEqual(self.raw(),old);self.assertEqual(self.list()['counts']['pending'],2)
 def test_concurrent_review_revision_rejected(self):
  self.prepare();self.decide(self.p1,'seen');self.decide(self.p2,'defer',revision=0,status=409);self.assertEqual(self.detail(self.p2)['status'],'pending')
 def test_external_library_edit_after_partial_apply_makes_remaining_stale(self):
  self.prepare();self.decide(self.p1,'apply');v=self.raw();self.req('PATCH',self.prefix+'/projects/'+self.p2,dict(version=v['version'],name='담당자 수정 업무'))
  self.assertTrue(self.detail(self.p2)['stale']);self.decide(self.p2,'apply',status=409);self.assertEqual(self.list('?status=stale')['total'],1)
 def test_unscanned_source_change_blocks_apply(self):
  self.prepare();(self.source/'비품.txt').write_text('내용이 바뀌었습니다.',encoding='utf-8');self.assertTrue(self.detail(self.p2)['stale']);old=self.raw();self.decide(self.p2,'apply',status=409);self.assertEqual(self.raw(),old)
 def test_confirmed_classification_is_protected(self):
  self.prepare();self.v=self.req('PATCH',self.prefix+'/files/'+self.fid,dict(version=self.v['version'],project_ids=[self.p1],reason='원문과 업무 담당자가 확인한 분류'))
  self.run=self.start(self.out);self.rid=self.run['id'];self.assertTrue(self.detail(self.p1)['assignments'][0]['protected']);self.decide(self.p1,'apply');self.assertEqual(self.raw()['files'][self.fid]['project_ids'],[self.p1]);self.assertIn('ai_note',self.raw()['projects'][self.p1])
 def test_deferred_requires_explicit_reopen_before_apply(self):
  self.prepare();self.decide(self.p1,'defer');self.decide(self.p1,'apply',status=409);self.decide(self.p1,'reopen');self.decide(self.p1,'apply');self.decide(self.p1,'apply',status=409)
 def test_legacy_whole_run_apply_or_dismiss_blocked_after_work_review(self):
  self.prepare();self.decide(self.p1,'seen');self.req('POST',self.prefix+'/ai-runs/'+self.rid+'/apply',dict(version=self.v['version'],file_ids=[self.fid]),409);self.req('POST',self.prefix+'/ai-runs/'+self.rid+'/dismiss',dict(version=self.v['version']),409)
 def test_search_status_pagination_and_no_model_call_when_listing(self):
  self.prepare()
  with patch.object(folder_ai,'call_model') as call:
   self.assertEqual(self.list('?query=컴퓨터')['total'],0);self.assertEqual(self.list('?query=비품')['total'],1);self.assertEqual(len(self.list('?limit=1&offset=1')['items']),1);self.assertEqual(self.list('?library_id=unknown')['total'],0);call.assert_not_called()
 def test_multiple_libraries_and_duplicate_work_names_do_not_mix(self):
  self.prepare();original=self.rid
  v=self.req('POST','/libraries',dict(name='두 번째 자료함',roots=[str(self.source)]),201)
  with folders.db() as c:
   r=folder_ai.stored(c,self.key,original);r.update(id='other-run',library_id=v['id'],base_version=v['version']);c.execute('INSERT INTO folder_ai_runs VALUES(?,?,?,?)',(r['id'],v['id'],'completed',folders.encode(r)))
  self.assertEqual(self.list()['total'],4);self.assertEqual(self.list('?library_id='+self.key)['total'],2);self.decide(self.p1,'defer');self.assertEqual(self.list('?library_id='+v['id'])['counts']['pending'],2)
 def test_old_full_applied_runs_display_history_without_reapplication(self):
  self.prepare();self.req('POST',self.prefix+'/ai-runs/'+self.rid+'/apply',dict(version=self.v['version'],file_ids=[self.fid,self.f2]));self.assertEqual(self.list('?status=applied')['total'],2);self.decide(self.p1,'apply',status=409)
 def test_bad_target_duplicate_selection_and_no_change_apply_rollback(self):
  self.prepare();self.req('GET',f'/change-inbox/{self.key}/{self.rid}?target=unknown',status=404);self.decide(self.p1,'apply',file_ids=[self.fid,self.fid],status=422);self.decide(self.p1,'apply',file_ids=[],apply_notes=False,status=422)
 def test_stale_can_be_deferred_but_not_reopened(self):
  self.prepare();v=self.raw();self.req('POST',self.prefix+'/projects',dict(version=v['version'],name='다른 사용자 변경'),201);self.decide(self.p1,'defer');self.decide(self.p1,'reopen',status=409)
 def test_queue_holds_after_partial_and_releases_after_all_decisions(self):
  self.prepare()
  with folders.db() as c:
   r=folder_ai.stored(c,self.key,self.rid);r['trigger']='watch';c.execute('UPDATE folder_ai_runs SET payload=? WHERE id=?',(folders.encode(r),self.rid));folder_watch.put(c,self.key,dict(enabled=True,profile='gemma',interval=5,pending={self.f2:self.raw()['files'][self.f2]['sha256']},changes=[],blocked=False))
  self.decide(self.p1,'apply');self.assertIsNone(folder_watch.reserve());self.decide(self.p2,'defer');self.assertIsNotNone(folder_watch.reserve())
 def test_report_includes_review_history_and_no_credentials(self):
  self.prepare();self.decide(self.p1,'seen');r=self.client.get('/api/folders/change-inbox/report.json');self.assertEqual(r.status_code,200);self.assertIn('no-store',r.headers['cache-control']);self.assertNotIn('unit-private-secret',r.text);self.assertEqual(r.json()['total'],2)

 def test_new_projects_can_be_applied_one_at_a_time(self):
  self.prepare();out=copy.deepcopy(self.out);out['new_projects']=[dict(key='n1',name='어르신 스마트폰 수업'),dict(key='n2',name='부서 비품 실물 수량 조사')]
  for a in out['assignments']:a['project']='new:n1' if a['file_id']==self.fid else 'new:n2'
  for i,note in enumerate(out['projects']):note['project']='new:n'+str(i+1)
  self.run=self.start(out);self.rid=self.run['id'];self.decide('new:n1','apply');self.assertFalse(self.detail('new:n2')['stale']);self.decide('new:n2','apply');v=self.raw();self.assertNotEqual(v['files'][self.fid]['project_ids'],v['files'][self.f2]['project_ids']);self.assertEqual(len([p for p in v['projects'].values() if p.get('ai_note')]),2)
 def test_corrupt_response_after_completed_run_rolls_back(self):
  self.prepare()
  with folders.db() as c:
   r=folder_ai.stored(c,self.key,self.rid);r['response_text']='not JSON';c.execute('UPDATE folder_ai_runs SET payload=? WHERE id=?',(folders.encode(r),self.rid))
  old=self.raw();self.decide(self.p1,'apply',status=422);self.assertEqual(self.raw(),old)

 def test_bounded_history_coverage_and_pagination_are_explicit(self):
  self.prepare()
  with patch.object(change_inbox,'MAX_RUNS',0):
   result=self.list();self.assertTrue(result['truncated']);self.assertEqual(result['scanned_runs'],0);self.assertEqual(result['total_runs'],1)
 def test_common_classification_apply_and_review_history_export(self):
  self.prepare();out=copy.deepcopy(self.out);out['assignments'][1]['project']='common';out['projects']=out['projects'][:1];self.run=self.start(out);self.rid=self.run['id']
  self.decide('common','seen');self.decide('common','apply');self.assertEqual(self.raw()['files'][self.f2]['bucket'],'common');data=self.list('?status=applied');self.assertEqual(data['items'][0]['target'],'common');self.assertEqual(len(data['items'][0]['history']),2)
