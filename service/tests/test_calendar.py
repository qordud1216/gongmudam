"""Calendar API contract tests, with every backing store isolated per test."""
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import adhoc, calendar_api, folders, store, tracker, travel_api


class CalendarApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.old_store = (store.DATA, store.LIBRARY, store.DB_PATH, store._conn)
        if store._conn:
            store._conn.close()
        store._conn = None
        store.DATA = self.data
        store.LIBRARY = self.data / 'library'
        store.DB_PATH = self.data / 'seomu.db'
        self.patches = [
            patch.object(calendar_api, 'DB_PATH', self.data / 'calendar.db'),
            patch.object(travel_api, 'DB_PATH', self.data / 'travel.db'),
            patch.object(adhoc, 'DB_PATH', self.data / 'adhoc.db'),
            patch.object(folders, 'DB_PATH', self.data / 'folders.db'),
        ]
        for p in self.patches:
            p.start()
        store.conn()
        travel_api.initialize()
        adhoc.initialize()
        folders.initialize()
        calendar_api.initialize()
        app = FastAPI()
        app.include_router(calendar_api.router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches):
            p.stop()
        if store._conn:
            store._conn.close()
        store.DATA, store.LIBRARY, store.DB_PATH, store._conn = self.old_store
        self.temp.cleanup()

    def event(self, title='계획 검토', start='2026-11-02T10:00:00+09:00', end='2026-11-02T11:00:00+09:00', **changes):
        return {'title': title, 'start': start, 'end': end} | changes

    def create(self, data=None, status=201):
        response = self.client.post('/api/calendar/events', json=data or self.event())
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def listing(self, start='2026-11-01', end='2026-12-31'):
        response = self.client.get('/api/calendar/events', params={'start': start, 'end': end})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['events']

    def test_create_update_persists_and_rejects_stale_versions(self):
        item = self.create()
        key = item['id']
        self.assertEqual(item['version'], 1)
        self.assertEqual(self.client.get(f'/api/calendar/events/{key}').json()['event']['title'], '계획 검토')
        changed = self.event(title='수정된 검토')
        r = self.client.patch(f'/api/calendar/events/{key}', json={'version': 1, 'event': changed})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['version'], 2)
        stale = self.client.patch(f'/api/calendar/events/{key}', json={'version': 1, 'event': changed})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.client.get(f'/api/calendar/events/{key}').json()['event']['title'], '수정된 검토')

    def test_all_day_end_is_exclusive_in_listing_and_ics(self):
        self.create(self.event('출장', '2026-11-02', '2026-11-04', all_day=True))
        event = self.listing('2026-11-01', '2026-11-05')[0]
        self.assertEqual((event['start'], event['end'], event['allDay']), ('2026-11-02', '2026-11-04', True))
        ics = self.client.get('/api/calendar/export.ics', params={'start': '2026-11-01', 'end': '2026-11-05'}).text
        self.assertIn('DTSTART;VALUE=DATE:20261102', ics)
        self.assertIn('DTEND;VALUE=DATE:20261104', ics)

    def test_timezone_aware_input_normalizes_to_kst_and_naive_is_rejected(self):
        item = self.create(self.event(start='2026-11-02T01:00:00Z', end='2026-11-02T02:00:00Z'))
        self.assertEqual(item['event']['start'], '2026-11-02T10:00:00+09:00')
        invalid = self.client.post('/api/calendar/events', json=self.event(start='2026-11-02T10:00:00', end='2026-11-02T11:00:00'))
        self.assertEqual(invalid.status_code, 422)

    def test_weekly_recurrence_expands_on_expected_dates(self):
        data = self.event(start='2026-11-02T10:00:00+09:00', end='2026-11-02T11:00:00+09:00',
                          recurrence='weekly', repeat_until='2026-11-23')
        self.create(data)
        got = [x['start'][:10] for x in self.listing('2026-11-01', '2026-11-30')]
        self.assertEqual(got, ['2026-11-02', '2026-11-09', '2026-11-16', '2026-11-23'])

    def test_monthly_day_31_skips_months_without_that_day(self):
        self.create(self.event(start='2026-01-31T10:00:00+09:00', end='2026-01-31T11:00:00+09:00',
                               recurrence='monthly', repeat_until='2026-05-31'))
        got = [x['start'][:10] for span in (('2026-01-01', '2026-04-01'), ('2026-04-01', '2026-06-01'))
               for x in self.listing(*span)]
        self.assertEqual(got, ['2026-01-31', '2026-03-31', '2026-05-31'])

    def test_occurrence_move_keeps_original_identity_and_series_version(self):
        series = self.create(self.event(start='2026-11-02T10:00:00+09:00', end='2026-11-02T11:00:00+09:00',
                                        recurrence='weekly', repeat_until='2026-11-16'))
        original = '2026-11-09T10:00:00+09:00'
        moved = self.event(title='일정 이동', start='2026-11-10T13:00:00+09:00', end='2026-11-10T14:00:00+09:00')
        response = self.client.patch(f"/api/calendar/events/{series['id']}", json={'version': 1, 'scope': 'occurrence', 'occurrence': original, 'event': moved})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['version'], 2)
        self.assertEqual(response.json()['occurrence'], original)
        listing = self.listing()
        changed = next(e for e in listing if e['extendedProps']['occurrence'] == original)
        self.assertEqual(changed['start'], moved['start'])
        self.assertTrue(changed['id'].endswith('@' + original))

    def test_cancelling_single_occurrence_omits_it_without_removing_series(self):
        series = self.create(self.event(recurrence='weekly', repeat_until='2026-11-16'))
        original = '2026-11-09T10:00:00+09:00'
        response = self.client.post(f"/api/calendar/events/{series['id']}/delete", json={'version': 1, 'scope': 'occurrence', 'occurrence': original})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([e['start'][:10] for e in self.listing()], ['2026-11-02', '2026-11-16'])
        detail = self.client.get(f"/api/calendar/events/{series['id']}", params={'occurrence': original})
        self.assertEqual(detail.status_code, 404)
        surviving = self.client.get(f"/api/calendar/events/{series['id']}").json()
        self.assertEqual(surviving['version'], 2)

    def test_series_rule_change_with_exception_is_rejected_without_data_loss(self):
        series = self.create(self.event(recurrence='weekly', repeat_until='2026-11-16'))
        original = '2026-11-09T10:00:00+09:00'
        self.client.post(f"/api/calendar/events/{series['id']}/delete", json={'version': 1, 'scope': 'occurrence', 'occurrence': original})
        changed = self.event(start='2026-11-03T10:00:00+09:00', end='2026-11-03T11:00:00+09:00', recurrence='weekly', repeat_until='2026-11-17')
        response = self.client.patch(f"/api/calendar/events/{series['id']}", json={'version': 2, 'event': changed})
        self.assertEqual(response.status_code, 422)
        current = self.client.get(f"/api/calendar/events/{series['id']}").json()
        self.assertEqual(current['version'], 2)
        self.assertEqual(current['series']['start'], series['event']['start'])
        self.assertEqual(len(self.listing()), 2)

    def test_work_link_requires_existing_matching_kind_and_id(self):
        self.create(self.event(work_kind='travel', work_id='missing'), status=422)

    def test_overlap_is_reported_and_free_slots_exclude_busy_time(self):
        self.create(self.event(title='회의', start='2026-11-02T10:00:00+09:00', end='2026-11-02T10:30:00+09:00'))
        overlapping = self.create(self.event(title='검토', start='2026-11-02T10:15:00+09:00', end='2026-11-02T10:45:00+09:00'))
        self.assertTrue(any(c['title'] == '회의' for c in overlapping['conflicts']))
        slots = self.client.get('/api/calendar/free-slots', params={'date': '2026-11-02', 'minutes': 30}).json()['slots']
        self.assertFalse(any(x['start'] < '2026-11-02T10:30:00+09:00' and x['end'] > '2026-11-02T10:00:00+09:00' for x in slots))

    def test_export_folds_utf8_lines_and_escapes_injection_characters(self):
        self.create(self.event('회의; 제목, 확인\n다음 줄', notes='경로\\내용\n둘째 줄' + '가' * 100, location='서울, 본관'))
        response = self.client.get('/api/calendar/export.ics', params={'start': '2026-11-01', 'end': '2026-11-03'})
        self.assertEqual(response.status_code, 200)
        raw = response.content
        self.assertIn('SUMMARY:회의\\; 제목\\, 확인\\n다음 줄'.encode(), raw)
        self.assertIn('DESCRIPTION:경로\\\\내용\\n둘째 줄'.encode(), raw)
        self.assertNotIn('\r\n다음 줄'.encode(), raw)
        self.assertTrue(all(len(line) <= 75 for line in raw.split(b'\r\n') if line))
        self.assertTrue(any(line.startswith(b' ') for line in raw.split(b'\r\n')))

    def test_time_export_uses_utc(self):
        self.create(self.event(start='2026-11-02T10:00:00+09:00', end='2026-11-02T11:00:00+09:00'))
        ics = self.client.get('/api/calendar/export.ics', params={'start': '2026-11-02', 'end': '2026-11-03'}).text
        self.assertIn('DTSTART:20261102T010000Z', ics)
        self.assertIn('DTEND:20261102T020000Z', ics)

    def test_calendar_can_query_and_edit_without_mutating_source_database_records(self):
        case_id = 'calendar-travel-case'
        trip = {'destination': '부산', 'purpose': '회의', 'start_date': '2026-11-10', 'end_date': '2026-11-11'}
        org_id = 'org-central'
        with travel_api.db() as c:
            org = c.execute('SELECT id FROM organizations LIMIT 1').fetchone()
            org_id = org['id']
            c.execute('INSERT INTO travel_cases(id,organization_id,profile_snapshot,trip_json,rule_snapshot,parse_issues,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                      (case_id, org_id, '{}', json.dumps(trip, ensure_ascii=False), '{}', '[]', 1, 'now', 'now'))
        with adhoc.db() as c:
            settings = {'title': '명단 취합', 'deadline': '2026-11-12', 'event_date': '2026-11-20'}
            c.execute('INSERT INTO jobs VALUES(?,?,?,?)', ('calendar-collection-job', 1, json.dumps(settings, ensure_ascii=False), 'now'))
        linked = self.create(self.event('연결 일정', work_kind='travel', work_id=case_id))
        self.assertEqual(linked['event']['work_id'], case_id)
        invalid = self.client.patch(f"/api/calendar/events/{linked['id']}", json={'version': 1, 'event': self.event('잘못된 연결', work_kind='collection', work_id='missing')})
        self.assertEqual(invalid.status_code, 422)
        with calendar_api.db() as c:
            calendar_count_before = c.execute('SELECT COUNT(*) FROM calendar_events').fetchone()[0]
        with patch.object(tracker, 'overview', return_value={'upcoming': [{'task_id': 'tracked-1', 'task': '보고서', 'no': 2, 'due': '2026-11-13', 'title': '결과 정리'}]}):
            projected = self.listing()
            source_ids = {e['extendedProps']['work_id'] for e in projected}
            self.assertIn(case_id, source_ids)
            self.assertIn('calendar-collection-job', source_ids)
            self.assertIn('tracked-1', source_ids)
            self.assertEqual(sum(e['extendedProps']['source'] == 'manual' for e in projected), 1)
            with travel_api.db() as c:
                c.execute('UPDATE travel_cases SET trip_json=? WHERE id=?', (json.dumps(trip | {'start_date': '2026-11-15', 'end_date': '2026-11-16'}), case_id))
            refreshed = self.listing()
        travel_item = next(e for e in refreshed if e['extendedProps']['work_id'] == case_id and e['extendedProps']['source'] == 'travel')
        self.assertEqual((travel_item['start'], travel_item['end']), ('2026-11-15', '2026-11-17'))
        with calendar_api.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM calendar_events').fetchone()[0], calendar_count_before)


    def test_series_create_reports_conflict_on_later_occurrence(self):
        self.create(self.event('나중 회의', '2026-11-09T10:00:00+09:00', '2026-11-09T11:00:00+09:00'))
        planned = self.create(self.event('매주 점검', '2026-11-02T10:00:00+09:00', '2026-11-02T11:00:00+09:00',
                                          recurrence='weekly', repeat_until='2026-11-16'))
        self.assertTrue(any(c['title'] == '나중 회의' and c['planned_start'] == '2026-11-09T10:00:00+09:00'
                            for c in planned['conflicts']), planned['conflicts'])

    def test_series_title_edit_after_first_occurrence_cancel_keeps_cancelled_date_absent(self):
        series = self.create(self.event(recurrence='weekly', repeat_until='2026-11-16'))
        original = '2026-11-02T10:00:00+09:00'
        cancelled = self.client.post(f"/api/calendar/events/{series['id']}/delete",
                                     json={'version': 1, 'scope': 'occurrence', 'occurrence': original})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        edited = self.client.patch(f"/api/calendar/events/{series['id']}", json={
            'version': 2, 'scope': 'series',
            'event': self.event('매주 수정된 점검', recurrence='weekly', repeat_until='2026-11-16')})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()['event']['title'], '매주 수정된 점검')
        dates = [e['start'][:10] for e in self.listing() if e['extendedProps']['event_id'] == series['id']]
        self.assertEqual(dates, ['2026-11-09', '2026-11-16'])

    def test_series_title_edit_checks_moved_exception_and_ignores_cancelled_original(self):
        series = self.create(self.event(recurrence='weekly', repeat_until='2026-11-23'))
        cancelled_original = '2026-11-09T10:00:00+09:00'
        self.client.post(f"/api/calendar/events/{series['id']}/delete",
                         json={'version': 1, 'scope': 'occurrence', 'occurrence': cancelled_original})
        self.create(self.event('취소된 원래 시각 점유', '2026-11-09T10:00:00+09:00', '2026-11-09T11:00:00+09:00'))
        self.create(self.event('이동된 시각 점유', '2026-11-10T10:00:00+09:00', '2026-11-10T11:00:00+09:00'))
        moved_original = '2026-11-16T10:00:00+09:00'
        moved = self.event('한 번 이동', '2026-11-10T10:00:00+09:00', '2026-11-10T11:00:00+09:00')
        response = self.client.patch(f"/api/calendar/events/{series['id']}", json={
            'version': 2, 'scope': 'occurrence', 'occurrence': moved_original, 'event': moved})
        self.assertEqual(response.status_code, 200, response.text)
        whole_edit = self.client.patch(f"/api/calendar/events/{series['id']}", json={
            'version': 3, 'scope': 'series',
            'event': self.event('전체 일정 이름 변경', recurrence='weekly', repeat_until='2026-11-23')})
        self.assertEqual(whole_edit.status_code, 200, whole_edit.text)
        conflicts = whole_edit.json()['conflicts']
        self.assertEqual([c['title'] for c in conflicts], ['이동된 시각 점유'], conflicts)
        self.assertTrue(all(c['planned_start'] == moved['start'] for c in conflicts))

    def test_generic_collection_event_date_uses_basis_label(self):
        settings = {'title': '일반 의견 취합', 'event_date': '2026-11-20', 'deadline': '',
                    'template_snapshot': {'kind': 'generic'}}
        with adhoc.db() as c:
            c.execute('INSERT INTO jobs VALUES(?,?,?,?)',
                      ('generic-calendar-job', 1, json.dumps(settings, ensure_ascii=False), 'now'))
        event = next(e for e in self.listing() if e['extendedProps']['event_id'] == 'collection:generic-calendar-job:education')
        self.assertEqual(event['start'], '2026-11-20')
        self.assertIn('기준일', event['title'])
        self.assertNotIn('교육일', event['title'])
if __name__ == '__main__':
    unittest.main()


