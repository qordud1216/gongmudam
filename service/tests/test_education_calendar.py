"""Education deadline edits preserve roster semantics and use existing completion rules."""
import json
import unittest
from unittest.mock import patch
from tests import test_calendar as fixtures
from app import adhoc, adhoc_workflow, calendar_api, education_calendar, toolbox


class EducationCalendarTest(unittest.TestCase):
    def setUp(self):
        fixtures.CalendarApiTest.setUp(self)
        self.client.app.include_router(education_calendar.router)
        self.client.app.include_router(adhoc.router)
        self.client.app.include_router(toolbox.router)
        toolbox.initialize()
        r=self.client.post('/api/adhoc/jobs',json=dict(situation='교육 희망자를 부서별로 취합해 주세요.',title='검증 교육',course='업무 교육',event_date='2026-11-06',deadline='2026-10-30',departments=['총무팀','교육팀']))
        self.assertEqual(r.status_code,201,r.text)
        self.key=r.json()['id']

    tearDown=fixtures.CalendarApiTest.tearDown

    def panel(self,step=None):
        r=self.client.get('/api/calendar/education/'+self.key,params={'step_id':step} if step else {})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def schedule(self,step,due,status=200,**extra):
        p=self.panel()
        r=self.client.patch('/api/calendar/education/'+self.key+'/schedule',json=dict(
            revision=p['revision'],data_version=p['data_version'],action='schedule',step_id=step,due_date=due,**extra))
        self.assertEqual(r.status_code,status,r.text)
        return r.json()

    def workflow(self,step,action,**kw):
        p=self.panel()
        r=self.client.patch('/api/adhoc/jobs/'+self.key+'/workflow',json=dict(revision=p['revision'],data_version=p['data_version'],action=action,step_id=step,**kw))
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def events(self):
        return self.client.get('/api/calendar/events',params={'start':'2026-10-01','end':'2026-11-10'}).json()['events']

    def step(self,p,key):return next(s for s in p['steps'] if s['id']==key)

    def ready_export(self):
        for department in ('총무팀','교육팀'):
            p=self.panel()
            r=self.client.post(f'/api/adhoc/jobs/{self.key}/empty-replies',json=dict(version=p['data_version'],department=department,reason='담당 부서의 없음 회신 확인'))
            self.assertEqual(r.status_code,200,r.text)
        p=self.panel()
        r=self.client.post(f'/api/adhoc/jobs/{self.key}/finalize',json={'version':p['data_version']})
        self.assertEqual(r.status_code,201,r.text)
        return r.json()

    def test_defaults_do_not_invent_deadlines_and_get_is_read_only(self):
        with adhoc.db() as c:before=list(c.iterdump())
        p=self.panel()
        self.assertEqual(len(p['steps']),5)
        self.assertEqual(self.step(p,'collect')['due_date'],'2026-10-30')
        self.assertTrue(all(s['due_date'] is None for s in p['steps'] if s['kind']!='collect'))
        self.assertEqual(p['summary']['missing'],2)
        self.assertEqual(p['departments'][0]['status'],'미회신')
        self.assertIn('?step=intake#job-',p['workflow_url'])
        events=self.events()
        self.assertEqual(len(events),2)
        self.assertTrue(all(e['extendedProps']['education_job'] for e in events))
        with adhoc.db() as c:self.assertEqual(list(c.iterdump()),before)

    def test_stage_plan_changes_revision_only_and_keeps_current_export(self):
        self.ready_export();before=self.panel()
        result=self.schedule('review','2026-11-03')
        self.assertEqual(result['data_version'],before['data_version'])
        self.assertEqual(result['revision'],before['revision']+1)
        self.assertTrue(result['resources']['exports'][0]['is_current'])
        item=next(e for e in self.events() if e['extendedProps'].get('education_step_id')=='review')
        self.assertEqual(item['start'],'2026-11-03')
        self.assertFalse(item['editable'])
        self.assertIn('?step=review#job-',item['extendedProps']['work_href'])
        self.schedule('review',None)
        self.assertFalse(any(e['extendedProps'].get('education_step_id')=='review' for e in self.events()))

    def test_schedule_change_marks_completed_step_for_review(self):
        self.workflow('intake','complete',confirmed=True)
        self.assertEqual(self.step(self.panel(),'intake')['status'],'done')
        p=self.schedule('intake','2026-10-28')
        self.assertEqual(self.step(p,'intake')['status'],'needs_review')
        self.assertTrue(self.step(p,'intake')['completed_at'])
        self.assertEqual(p['data_version'],1)

    def test_reply_deadline_confirmation_validation_and_export_impact(self):
        self.ready_export();self.workflow('collect','complete',confirmed=True)
        before=self.panel()
        for due,extra in [('2026-11-07',{'confirmed':True}),(None,{'confirmed':True}),('2026-11-02',{})]:
            self.schedule('collect',due,status=422,**extra)
            self.assertEqual(self.panel()['data_version'],before['data_version'])
        after=self.schedule('collect','2026-11-02',confirmed=True)
        self.assertEqual(after['reply_deadline'],'2026-11-02')
        self.assertEqual(after['data_version'],before['data_version']+1)
        self.assertEqual(after['revision'],before['revision']+1)
        self.assertFalse(after['resources']['exports'][0]['is_current'])
        self.assertEqual(self.step(after,'collect')['status'],'needs_review')
        old=after['resources']['exports'][0]
        self.assertEqual(self.client.get(old['url']).status_code,200)
        self.assertIn('2026-11-02',after['request_draft'])
        with adhoc.db() as c:
            history=json.loads(c.execute('SELECT detail FROM job_workflow_history WHERE job_id=? ORDER BY id DESC',(self.key,)).fetchone()['detail'])
        self.assertEqual(history['schedule'],dict(before='2026-10-30',after='2026-11-02',source_changed=True))

    def test_stale_versions_fail_and_same_date_is_idempotent(self):
        old=self.panel();self.schedule('intake','2026-10-26')
        r=self.client.patch('/api/calendar/education/'+self.key+'/schedule',json=dict(revision=old['revision'],data_version=old['data_version'],action='schedule',step_id='report',due_date='2026-11-05'))
        self.assertEqual(r.status_code,409)
        p=self.panel();same=self.schedule('intake','2026-10-26')
        self.assertEqual(p['revision'],same['revision'])
        self.client.post(f'/api/adhoc/jobs/{self.key}/empty-replies',json=dict(version=p['data_version'],department='총무팀',reason='해당 부서의 없음 회신 확인'))
        stale=self.client.patch('/api/calendar/education/'+self.key+'/schedule',json=dict(revision=p['revision'],data_version=p['data_version'],action='schedule',step_id='report',due_date='2026-11-05'))
        self.assertEqual(stale.status_code,409)
        self.assertEqual(self.panel()['data_version'],p['data_version']+1)

    def test_custom_step_identity_survives_move_archive_restore(self):
        v=self.workflow(None,'add',title='부서장 확인',before_id='report')
        step=next(s for s in v['workflow']['steps'] if s['kind']=='custom')['id']
        self.schedule(step,'2026-11-04');self.workflow(step,'move',before_id='intake')
        self.assertEqual(self.panel()['steps'][0]['id'],step)
        self.workflow(step,'archive')
        self.assertFalse(any(e['extendedProps'].get('education_step_id')==step for e in self.events()))
        self.workflow(step,'restore')
        self.assertEqual(self.step(self.panel(),step)['due_date'],'2026-11-04')

    def test_existing_completion_checks_and_empty_reply_actions_remain_authoritative(self):
        p=self.panel()
        r=self.client.patch(f'/api/adhoc/jobs/{self.key}/workflow',json=dict(revision=p['revision'],data_version=p['data_version'],step_id='collect',action='complete',confirmed=True))
        self.assertEqual(r.status_code,422)
        self.ready_export()
        self.assertEqual(self.panel()['summary']['missing'],0)
        self.assertTrue(self.step(self.panel(),'collect')['can_complete'])
        self.workflow('collect','complete',confirmed=True)
        item=next(e for e in self.events() if e['extendedProps'].get('education_step_id')=='collect')
        self.assertIn('완료',item['title'])

    def test_registered_references_show_stale_and_block_completion(self):
        reference=dict(origin='template',id='source',unit=0,sha256='a'*64,title='등록 서식',kind='기관 취합 서식',text='원문',href='/api/adhoc/templates/source/original')
        with patch.object(adhoc_workflow,'catalog',return_value=[reference]):
            self.workflow('intake','edit',references=[{k:reference[k] for k in ('origin','id','unit','sha256')}])
            self.assertTrue(self.step(self.panel(),'intake')['references'][0]['current'])
        with patch.object(adhoc_workflow,'catalog',return_value=[]):
            s=self.step(self.panel(),'intake')
            self.assertFalse(s['references'][0]['current']);self.assertFalse(s['can_complete'])

    def test_missing_or_archived_step_rejected_and_persistence(self):
        self.assertEqual(self.client.get('/api/calendar/education/missing').status_code,404)
        self.assertEqual(self.client.get('/api/calendar/education/'+self.key,params={'step_id':'missing'}).status_code,404)
        self.schedule('report','2026-11-05')
        adhoc.initialize();calendar_api.initialize()
        self.assertEqual(self.step(self.panel(),'report')['due_date'],'2026-11-05')

    def test_overdue_is_textual_and_finished_steps_are_not_overdue(self):
        p=self.schedule('intake','2000-01-01')
        self.assertTrue(self.step(p,'intake')['overdue'])
        old=self.client.get('/api/calendar/events',params={'start':'2000-01-01','end':'2000-01-03'}).json()['events'][0]
        self.assertIn('지연',old['title'])
        self.workflow('intake','complete',confirmed=True)
        self.assertFalse(self.step(self.panel(),'intake')['overdue'])


if __name__=='__main__':unittest.main()
