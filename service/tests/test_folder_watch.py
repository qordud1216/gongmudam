import copy,json,os,unittest
from unittest.mock import patch
from fastapi import HTTPException
from app import folders,folder_ai,folder_watch
from tests import test_folder_ai as ai_tests

class FolderWatchTest(unittest.TestCase):
 setUp=ai_tests.FolderAITest.setUp
 tearDown=ai_tests.FolderAITest.tearDown
 req=ai_tests.FolderAITest.req
 output=ai_tests.FolderAITest.output
 begin=ai_tests.FolderAITest.begin
 apply=ai_tests.FolderAITest.apply
 def setup_watch(self):
  folder_watch.initialize();self.client.app.include_router(folder_watch.router)
  return self.req('PUT',self.prefix+'/watch',dict(enabled=True,profile='gemma',interval=5))
 def update_source(self,text=None):
  (self.source/'메모.txt').write_text(text or '오는 2026년 11월 6일 어르신 스마트폰 수업을 준비합니다.\n참석자 명단을 취합했고 좌석 배치 확인이 필요합니다.',encoding='utf-8')
 def settle(self,start=100):folder_watch.scan_one(self.key,start);folder_watch.scan_one(self.key,start+5)
 def raw(self):
  with folders.db() as c:return folders.get(c,self.key)
 def watch(self):return self.req('GET',self.prefix+'/watch')
 def test_off_by_default_and_enable_local_only(self):
  self.setup_watch();self.req('PUT',self.prefix+'/watch',dict(enabled=True,profile='external',interval=5),422)
  self.assertEqual(self.watch()['profile'],'gemma');self.req('PUT',self.prefix+'/watch',dict(enabled=True,profile='gemma',interval=1),422)
 def test_no_change_does_not_bump_version_or_call_ai(self):
  self.setup_watch();self.settle();self.assertEqual(self.raw()['version'],1);self.assertIsNone(folder_watch.reserve());self.assertEqual(self.watch()['pending_files'],0)
 def test_debounce_requires_two_identical_polls(self):
  self.setup_watch();self.update_source();folder_watch.scan_one(self.key,100);self.assertEqual(self.raw()['version'],1)
  self.update_source('다른 내용으로 저장 중입니다.');folder_watch.scan_one(self.key,105);self.assertEqual(self.raw()['version'],1)
  folder_watch.scan_one(self.key,110);self.assertEqual(self.raw()['version'],2)
 def test_add_and_modify_detected_without_manual_scan(self):
  self.setup_watch();self.update_source();(self.source/'회신.txt').write_text('참석자 명단을 확인하고 좌석 배치를 조정합니다.',encoding='utf-8');self.settle()
  self.assertEqual({x['kind'] for x in self.watch()['changes']},{'added','modified'});self.assertEqual(self.watch()['pending_files'],2)
 def test_touch_same_content_updates_stat_without_ai(self):
  self.setup_watch();p=self.source/'메모.txt';st=p.stat();os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns+10000000));self.settle()
  self.assertEqual(self.raw()['version'],1);self.assertEqual(self.watch()['pending_files'],0);folder_ai.verify_sources(list(self.raw()['files'].values()))
 def test_protected_multilink_and_saved_note_preserved(self):
  r,_=self.begin();self.v=self.apply(r);old=self.raw();pid=next(iter(old['projects']));self.setup_watch();self.update_source();self.settle()
  v=self.raw();f=v['files'][self.fid];self.assertTrue(f['confirmed']);self.assertTrue(f['manual']);self.assertEqual(f['project_ids'],old['files'][self.fid]['project_ids']);self.assertEqual(f['ai_assignment'],old['files'][self.fid]['ai_assignment']);self.assertEqual(v['projects'][pid]['ai_note'],old['projects'][pid]['ai_note']);self.assertTrue(f['content_changed'])
 def test_reservation_records_before_state_and_global_lock(self):
  self.setup_watch();self.update_source();self.settle();job=folder_watch.reserve();self.assertIsNotNone(job);self.assertIsNone(folder_watch.reserve())
  r=self.req('GET',self.prefix+'/ai-runs/'+job[0]);self.assertEqual(r['trigger'],'watch');self.assertIn('previous_state',r);self.assertEqual(r['changes'][0]['kind'],'modified');self.assertNotIn('secret',json.dumps(r))
 def test_actual_executor_mocked_adapter_and_no_autoapply(self):
  self.setup_watch();self.update_source();self.settle();before=copy.deepcopy(self.raw())
  out=self.output();out['projects'][0]['actions'][0]['evidence'][0].update(unit=2,quote='참석자 명단을 취합했고 좌석 배치 확인이 필요합니다.')
  with patch.object(folder_ai,'call_model',return_value=(json.dumps(out,ensure_ascii=False),{'actual_response':True,'backend':'test'})):
   folder_watch.analyze_one()
  r=self.req('GET',self.prefix+'/ai-runs')[0];self.assertEqual(r['status'],'completed');self.assertEqual(self.raw(),before);self.assertTrue(r['comparison']['projects']);self.assertFalse(r['applied'])
 def test_failed_batch_blocks_repeated_ai_and_retry_is_explicit(self):
  self.setup_watch();self.update_source();self.settle()
  with patch.object(folder_ai,'call_model',side_effect=ValueError('unit failure')) as call:
   folder_watch.analyze_one();folder_watch.analyze_one();self.assertEqual(call.call_count,1)
  self.assertTrue(self.watch()['blocked']);self.assertEqual(self.watch()['pending_files'],1)
  self.req('POST',self.prefix+'/watch/retry',{});self.assertFalse(self.watch()['blocked']);self.assertIsNotNone(folder_watch.reserve())
 def test_disable_stops_scan_and_reserve(self):
  self.setup_watch();self.update_source();self.req('PUT',self.prefix+'/watch',dict(enabled=False,profile='gemma',interval=5));self.settle();self.assertEqual(self.raw()['version'],1);self.assertIsNone(folder_watch.reserve())
 def test_read_failure_keeps_files_and_exposes_error(self):
  self.setup_watch()
  with patch.object(folders,'collect',return_value=({},['read failed'])):self.settle()
  self.assertEqual(self.raw()['version'],1);self.assertTrue(self.watch()['scan_error']);self.assertTrue(self.raw()['files'][self.fid]['present'])
 def test_missing_not_deleted_and_return_detected(self):
  self.setup_watch();p=self.source/'메모.txt';text=p.read_text(encoding='utf-8');p.unlink();self.settle();self.assertFalse(self.raw()['files'][self.fid]['present']);self.assertEqual(self.watch()['changes'][0]['kind'],'unavailable')
  p.write_text(text,encoding='utf-8');self.settle(110);self.assertTrue(self.raw()['files'][self.fid]['present']);self.assertEqual(self.watch()['pending_files'],1)
 def test_persistent_settings_survive_initialize(self):
  self.setup_watch();self.update_source();self.settle();folder_watch.initialize();self.assertTrue(self.watch()['enabled']);self.assertEqual(self.watch()['pending_files'],1)
 def test_pending_more_than_twelve_kept(self):
  self.setup_watch()
  for i in range(15):(self.source/f'new{i}.txt').write_text('부서 참석자 명단 취합 여부를 확인합니다.',encoding='utf-8')
  self.settle();job=folder_watch.reserve();self.assertEqual(len(job[2]['documents']),12);self.assertEqual(self.watch()['pending_files'],3)
 def test_stale_run_cannot_apply_and_new_version_requeues(self):
  self.setup_watch();self.update_source();self.settle();job=folder_watch.reserve();rid=job[0]
  with folders.db() as c:
   r=folder_ai.stored(c,self.key,rid);r.update(status='completed',result={'assignments':[],'projects':[]},response_text='{}');c.execute('UPDATE folder_ai_runs SET status=?,payload=? WHERE id=?',('completed',folders.encode(r),rid))
  self.assertIsNone(folder_watch.reserve());self.update_source('새로운 명단 회신 자료를 확인하고 좌석을 배치합니다.');self.settle(110)
  self.req('POST',self.prefix+'/ai-runs/'+rid+'/apply',dict(version=self.raw()['version'],file_ids=[]),409);self.assertIsNotNone(folder_watch.reserve())
 def test_comparison_uses_accepted_notes_and_action_changes(self):
  run={'previous_state':{'projects':{'p':{'ai_note':{'summary':{'text':'기존 요약'},'actions':[{'text':'이전 할 일'},{'text':'공통'}]}}},'files':{}},'changes':[]}
  c=folder_ai.change_comparison(run,{'assignments':[],'projects':[{'project':'p','summary':{'text':'새 요약'},'actions':[{'text':'새 할 일'},{'text':'공통'}]}]})['projects'][0]
  self.assertEqual(c['before_summary'],'기존 요약');self.assertEqual(c['actions_added'],['새 할 일']);self.assertEqual(c['actions_removed'],['이전 할 일']);self.assertEqual(c['actions_unchanged'],['공통'])
 def test_unsupported_file_detected_but_not_sent_to_ai(self):
  self.setup_watch();(self.source/'scan.png').write_bytes(b'fake image');self.settle();self.assertEqual(self.watch()['changes'][0]['kind'],'added');self.assertEqual(self.watch()['pending_files'],0)
 def test_concurrent_user_change_is_not_overwritten(self):
  self.setup_watch();self.update_source();original=folders.collect
  def collect(roots):
   result=original(roots)
   with folders.db() as c:
    c.execute('BEGIN IMMEDIATE');v=folders.get(c,self.key);folders.save(c,v,v['version'],'사용자 작업',{})
   return result
  with patch.object(folders,'collect',side_effect=collect):folder_watch.scan_one(self.key,100)
  self.assertEqual(self.raw()['version'],2);self.assertFalse(self.watch()['changes'])

 def test_dismiss_all_proposals_without_changing_accepted_state(self):
  self.setup_watch();self.update_source();self.settle()
  with patch.object(folder_ai,'call_model',return_value=(json.dumps(self.output(),ensure_ascii=False),{'actual_response':True})):folder_watch.analyze_one()
  r=self.req('GET',self.prefix+'/ai-runs')[0];before=self.raw()
  self.req('POST',self.prefix+'/ai-runs/'+r['id']+'/dismiss',{'version':before['version']});self.assertEqual(self.raw(),before);self.assertTrue(self.req('GET',self.prefix+'/ai-runs/'+r['id'])['dismissed'])
  self.req('POST',self.prefix+'/ai-runs/'+r['id']+'/apply',dict(version=before['version'],file_ids=[]),409)
 def test_related_context_is_marked_separately_from_changed_doc(self):
  self.setup_watch();self.update_source();self.settle();job=folder_watch.reserve();self.assertEqual(job[2]['documents'][0]['watch_role'],'changed_document');self.assertIn('watch_notice',job[2])
