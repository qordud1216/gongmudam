"""Reminder time windows, authoritative completion, and acknowledgement isolation."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from tests import test_calendar as fixtures
from app import adhoc, calendar_api, calendar_agenda as agenda, education_calendar, toolbox

NOW=datetime(2026,10,24,10,tzinfo=calendar_api.KST)


class AgendaTest(unittest.TestCase):
    def setUp(self):
        fixtures.CalendarApiTest.setUp(self)
        toolbox.initialize()
        agenda.initialize()
        self.client.app.include_router(agenda.router)
        self.client.app.include_router(adhoc.router)
        self.client.app.include_router(education_calendar.router)
        self.clock=patch.object(agenda,'now_kst',return_value=NOW);self.clock.start()

    def tearDown(self):
        self.clock.stop();fixtures.CalendarApiTest.tearDown(self)

    def education(self):
        r=self.client.post('/api/adhoc/jobs',json=dict(situation='교육 희망자 취합 업무입니다.',title='마감 확인 교육',course='합성 업무 교육',event_date='2026-11-06',deadline='2026-10-25',departments=['총무팀']))
        self.assertEqual(r.status_code,201,r.text);key=r.json()['id']
        for step,due in [('intake','2026-10-19'),('request','2026-10-24'),('review','2026-10-26')]:
            p=self.client.get('/api/calendar/education/'+key).json()
            r=self.client.patch('/api/calendar/education/'+key+'/schedule',json=dict(action='schedule',step_id=step,due_date=due,revision=p['revision'],data_version=p['data_version']))
            self.assertEqual(r.status_code,200,r.text)
        return key

    def get(self):
        r=self.client.get('/api/calendar/agenda');self.assertEqual(r.status_code,200,r.text);return r.json()

    def create(self,**kw):
        event=dict(title='직접 마감',start='2026-10-24',end='2026-10-25',all_day=True,kind='deadline')|kw
        r=self.client.post('/api/calendar/events',json=event);self.assertEqual(r.status_code,201,r.text);return r.json()

    def task(self,p,suffix):return next(t for t in p['tasks'] if t['id'].endswith(suffix))

    def test_empty_snapshot_defaults_and_get_does_not_write(self):
        with calendar_api.db() as c:before=list(c.iterdump())
        p=self.get();self.assertEqual(p['tasks'],[]);self.assertEqual(p['alerts'],[])
        self.assertEqual(p['preferences'],dict(revision=0,enabled=True,days=3))
        self.assertEqual((p['week_start'],p['week_end']),('2026-10-19','2026-10-25'))
        with calendar_api.db() as c:self.assertEqual(list(c.iterdump()),before)

    def test_week_imminent_overdue_and_unassigned_are_distinct(self):
        self.education();p=self.get()
        self.assertEqual(len(p['tasks']),5)
        self.assertTrue(self.task(p,':intake')['overdue'])
        self.assertFalse(self.task(p,':intake')['imminent'])
        self.assertTrue(self.task(p,':request')['imminent'])
        self.assertTrue(self.task(p,':collect')['in_week'])
        self.assertFalse(self.task(p,':review')['in_week'])
        self.assertTrue(self.task(p,':review')['imminent'])
        self.assertIsNone(self.task(p,':report')['due'])
        self.assertFalse(self.task(p,':report')['overdue'])
        self.assertEqual(len(p['alerts']),4)

    def test_time_deadline_boundary_kst_and_meetings_not_overdue(self):
        self.create(title='정각 마감',all_day=False,start='2026-10-24T01:00:00Z',end='2026-10-24T02:00:00Z')
        self.create(title='잠시 후 마감',all_day=False,start='2026-10-24T10:01:00+09:00',end='2026-10-24T11:00:00+09:00')
        self.create(title='지난 회의',kind='event',start='2026-10-23',end='2026-10-24')
        p=self.get();by={t['title']:t for t in p['tasks']}
        self.assertTrue(by['정각 마감']['overdue'])
        self.assertTrue(by['잠시 후 마감']['imminent'])
        self.assertFalse(by['지난 회의']['overdue']);self.assertFalse(by['지난 회의']['is_task'])
        self.assertEqual(len(p['alerts']),2)

    def test_read_is_not_completion_and_same_ack_is_idempotent(self):
        self.education();p=self.get();alert=p['alerts'][0]
        with adhoc.db() as c:before=list(c.iterdump())
        for _ in range(2):
            r=self.client.post('/api/calendar/agenda/alerts',json=dict(key=alert['key'],action='read'))
            self.assertEqual(r.status_code,200,r.text)
        after=self.get();self.assertNotIn(alert['key'],[a['key'] for a in after['alerts']])
        self.assertEqual(p['tasks'],after['tasks'])
        with adhoc.db() as c:self.assertEqual(list(c.iterdump()),before)

    def test_snooze_returns_next_day_at_nine_and_survives_initialize(self):
        self.create();key=self.get()['alerts'][0]['key']
        r=self.client.post('/api/calendar/agenda/alerts',json=dict(key=key,action='snooze'));self.assertEqual(r.status_code,200)
        agenda.initialize()
        self.assertEqual(self.get()['alerts'],[])
        with patch.object(agenda,'now_kst',return_value=NOW.replace(day=25,hour=8,minute=59)):
            self.assertEqual(self.get()['alerts'],[])
        with patch.object(agenda,'now_kst',return_value=NOW.replace(day=25,hour=9)):
            self.assertEqual(self.get()['alerts'][0]['key'],key)

    def test_completed_step_disappears_from_alerts_and_stale_ack_rejected(self):
        key=self.education();p=self.get();alert=next(a for a in p['alerts'] if a['task_id'].endswith(':request'))
        w=self.client.get('/api/calendar/education/'+key).json()
        r=self.client.patch('/api/adhoc/jobs/'+key+'/workflow',json=dict(revision=w['revision'],data_version=w['data_version'],step_id='request',action='complete',confirmed=True));self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.task(self.get(),':request')['status'],'done')
        self.assertNotIn(alert['key'],[a['key'] for a in self.get()['alerts']])
        self.assertEqual(self.client.post('/api/calendar/agenda/alerts',json=dict(key=alert['key'],action='read')).status_code,409)

    def test_changed_deadline_creates_new_alert_without_erasing_old_state(self):
        key=self.education();a=next(a for a in self.get()['alerts'] if a['task_id'].endswith(':collect'))
        self.client.post('/api/calendar/agenda/alerts',json=dict(key=a['key'],action='read'))
        p=self.client.get('/api/calendar/education/'+key).json()
        r=self.client.patch('/api/calendar/education/'+key+'/schedule',json=dict(revision=p['revision'],data_version=p['data_version'],step_id='collect',action='schedule',due_date='2026-10-26',confirmed=True))
        self.assertEqual(r.status_code,200,r.text)
        new=next(a for a in self.get()['alerts'] if a['task_id'].endswith(':collect'))
        self.assertNotEqual(a['key'],new['key'])
        with calendar_api.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM calendar_alert_states').fetchone()[0],1)

    def test_preferences_guard_range_disabled_and_reload(self):
        self.create()
        r=self.client.patch('/api/calendar/agenda/preferences',json=dict(revision=0,enabled=False,days=7))
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['revision'],1)
        self.assertEqual(self.get()['alerts'],[]);self.assertEqual(len(self.get()['tasks']),1)
        self.assertEqual(self.client.patch('/api/calendar/agenda/preferences',json=dict(revision=0,enabled=True,days=1)).status_code,409)
        self.assertEqual(self.client.patch('/api/calendar/agenda/preferences',json=dict(revision=1,enabled=True,days=15)).status_code,422)
        agenda.initialize();self.assertFalse(self.get()['preferences']['enabled'])

    def test_recurring_cancelled_occurrence_excluded_and_action_keeps_identity(self):
        e=self.create(start='2026-10-19',end='2026-10-20',recurrence='daily',repeat_until='2026-11-10')
        self.client.post('/api/calendar/events/'+e['id']+'/delete',json=dict(version=1,scope='occurrence',occurrence='2026-10-24'))
        p=self.get();self.assertFalse(any(t['due']=='2026-10-24' for t in p['tasks']))
        self.assertTrue(all(t['action']['event']['extendedProps']['recurrence']=='daily' for t in p['tasks']))
        self.assertTrue(all(t['action']['event']['extendedProps']['occurrence'] in t['id'] for t in p['tasks']))

    def test_unknown_alert_key_does_not_create_state(self):
        self.assertEqual(self.client.post('/api/calendar/agenda/alerts',json=dict(key='a'*64,action='read')).status_code,409)
        with calendar_api.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM calendar_alert_states').fetchone()[0],0)


if __name__=='__main__':unittest.main()
