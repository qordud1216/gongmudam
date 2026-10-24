import json
import unittest
from app import travel_api
import test_travel
import test_travel_files
import test_travel_package


class WorkflowTest(unittest.TestCase):
    setUp=test_travel.TravelApiTest.setUp
    tearDown=test_travel.TravelApiTest.tearDown
    request=test_travel.TravelApiTest.request
    create=test_travel.TravelApiTest.create
    evidence=test_travel.TravelApiTest.evidence
    decide=test_travel.TravelApiTest.decide
    upload=test_travel_files.ReceiptTest.upload
    confirm=test_travel_files.ReceiptTest.confirm
    prepared=test_travel_package.PackageTest.prepared
    draft=test_travel_package.PackageTest.draft

    def task(self,c,title='복귀 승차권 원본 확인',**changes):
        return self.request('POST',f"/cases/{c['id']}/tasks",dict(version=c['version'],workflow_revision=c['workflow_revision'],title=title,note='필요 자료를 대조해 확인',**changes),201)

    def change(self,c,action='done',reason='자료를 대조해 작업 완료',status=200):
        return self.request('PATCH',f"/cases/{c['id']}/tasks/{c['tasks'][0]['id']}",dict(version=c['version'],workflow_revision=c['workflow_revision'],action=action,reason=reason),status)

    def summary(self,c):return next(r for r in self.request('GET','/cases') if r['id']==c['id'])

    def calc(self,c):
        return self.request('POST',f"/cases/{c['id']}/calculate",dict(version=c['version'],grade='group2',conditions_confirmed=True,ordinary_fare_confirmed=True))

    def test_case_stages_follow_actual_data(self):
        c=self.create(organization_id='national-general',purpose='회의',end_date='2026-10-15',overnight=False)
        self.assertEqual(self.summary(c)['stage'],'evidence')
        c=self.evidence(c,test_travel_files.TEXT)
        self.assertEqual(self.summary(c)['stage'],'review')
        c=self.decide(c)
        self.assertEqual(self.summary(c)['stage'],'calculate')
        c=self.calc(c)
        self.assertEqual(self.summary(c)['stage'],'supplement')
        c=self.upload(c)
        self.assertEqual(self.summary(c)['stage'],'review')
        c=self.confirm(c)
        self.assertEqual(self.summary(c)['stage'],'recalculate')
        c=self.calc(c)
        self.assertEqual(self.summary(c)['stage'],'draft')
        self.draft(c)
        self.assertEqual(self.summary(c)['stage'],'handoff')

    def test_blocked_calculation_has_input_status(self):
        c=self.decide(self.evidence(self.create(),test_travel_files.TEXT));c=self.calc(c)
        self.assertEqual(self.summary(c)['stage'],'needs_input')
        self.assertIsNone(self.summary(c)['estimated_total'])

    def test_search_and_status_filter(self):
        c=self.create(destination='목포',purpose='현장점검')
        self.create(destination='부산')
        self.assertEqual([r['id'] for r in self.request('GET','/cases?q=목포')],[c['id']])
        self.assertEqual([r['id'] for r in self.request('GET','/cases?q=현장점검&stage=evidence')],[c['id']])
        self.assertEqual(len(self.request('GET','/cases?q=가람시청')),2)
        self.assertEqual(self.request('GET','/cases?q=없는단어'),[])
        self.request('GET','/cases?stage=invalid',status=422)
        self.request('GET','/cases?q='+'a'*201,status=422)

    def test_task_does_not_invalidate_financial_calculation(self):
        c=self.prepared();version=c['version'];amount=c['calculation']['result']['estimated_total']
        c=self.task(c)
        self.assertEqual(c['version'],version);self.assertEqual(c['workflow_revision'],1)
        self.assertFalse(c['calculation']['stale']);self.assertEqual(c['calculation']['result']['estimated_total'],amount)
        self.assertEqual(self.summary(c)['open_tasks'],1)
        self.assertEqual(self.summary(c)['stage'],'supplement')

    def test_task_completion_never_overrides_missing_original(self):
        c=self.decide(self.evidence(self.create(organization_id='national-general',purpose='회의',end_date='2026-10-15',overnight=False),test_travel_files.TEXT))
        c=self.calc(c);c=self.task(c);c=self.change(c)
        self.assertEqual(self.summary(c)['stage'],'supplement')
        self.assertGreater(self.summary(c)['required_count'],0)
        self.assertEqual(self.summary(c)['open_tasks'],0)

    def test_stale_workflow_revision_rejected_without_partial_save(self):
        c=self.create();self.task(c)
        self.request('POST',f"/cases/{c['id']}/tasks",dict(version=c['version'],workflow_revision=0,title='중복 동시 변경 검증'),409)
        latest=self.request('GET',f"/cases/{c['id']}")
        self.assertEqual(len(latest['tasks']),1);self.assertEqual(latest['workflow_revision'],1)

    def test_stale_case_version_rejected_on_task_write(self):
        c=self.create();self.evidence(c,test_travel_files.TEXT)
        self.request('POST',f"/cases/{c['id']}/tasks",dict(version=c['version'],workflow_revision=0,title='오래된 자료에서 추가'),409)

    def test_task_done_reopen_reason_and_history(self):
        c=self.task(self.create());self.change(c,reason='짧음',status=422)
        c=self.change(c);self.assertEqual(c['tasks'][0]['status'],'done')
        self.change(c,status=409)
        c=self.change(c,action='reopen',reason='추가 자료 대조가 필요함')
        self.assertEqual(c['tasks'][0]['status'],'open');self.assertEqual(c['workflow_revision'],3)
        self.assertEqual(sum(e['event_type']=='TASK_CHANGED' for e in c['events']),2)

    def test_task_cross_case_not_found(self):
        c=self.task(self.create());other=self.create()
        self.request('PATCH',f"/cases/{other['id']}/tasks/{c['tasks'][0]['id']}",dict(version=other['version'],workflow_revision=0,action='done',reason='다른 사건의 작업 접근'),404)
        self.assertEqual(self.request('GET',f"/cases/{other['id']}")['workflow_revision'],0)

    def test_task_change_marks_saved_draft_previous_content(self):
        c=self.prepared();d=self.draft(c)
        saved=self.request('GET',f"/cases/{c['id']}/drafts")['drafts'][0]
        self.assertTrue(saved['is_current'])
        c=self.task(c)
        saved=self.request('GET',f"/cases/{c['id']}/drafts")['drafts'][0]
        self.assertFalse(saved['is_current']);self.assertEqual(saved['id'],d['id'])
        self.draft(c)
        saved=self.request('GET',f"/cases/{c['id']}/drafts")['drafts']
        self.assertTrue(saved[0]['is_current']);self.assertEqual(saved[0]['workflow_revision'],1)
        self.assertFalse(saved[1]['is_current'])

    def test_task_snapshot_html_and_package_are_immutable(self):
        c=self.task(self.prepared(),title='<script>원본 재확인</script>');d=self.draft(c)
        first=self.client.get(d['package_url']).content
        page=self.client.get(d['json_url']+'/print').text
        self.assertIn('&lt;script&gt;원본 재확인&lt;/script&gt;',page);self.assertNotIn('<script>',page)
        codes=[i['code'] for i in self.client.get(d['package_check_url']).json()['checklist']]
        self.assertIn('OPEN_MANUAL_TASK',codes)
        c=self.change(c)
        self.assertEqual(first,self.client.get(d['package_url']).content)
        self.assertEqual(self.client.get(d['json_url']).json()['snapshot']['tasks'][0]['status'],'open')

    def test_legacy_draft_without_workflow_metadata(self):
        c=self.prepared();d=self.draft(c)
        with travel_api.db() as db:
            r=db.execute('SELECT snapshot FROM travel_drafts WHERE id=?',(d['id'],)).fetchone()
            snap=json.loads(r['snapshot']);snap.pop('tasks');snap.pop('workflow_revision')
            db.execute('UPDATE travel_drafts SET snapshot=? WHERE id=?',(json.dumps(snap),d['id']))
        saved=self.request('GET',f"/cases/{c['id']}/drafts")['drafts'][0]
        self.assertTrue(saved['is_current']);self.assertEqual(saved['workflow_revision'],0)
        self.assertEqual(self.client.get(d['package_url']).status_code,200)

    def test_unknown_case_saved_drafts_404(self):
        self.request('GET','/cases/unknown/drafts',status=404)


if __name__=='__main__':unittest.main()
