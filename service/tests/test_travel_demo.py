import hashlib
import io
import json
import unittest
import zipfile
from unittest.mock import patch
from app import travel_api
import test_travel


class DemoTest(unittest.TestCase):
    setUp=test_travel.TravelApiTest.setUp
    tearDown=test_travel.TravelApiTest.tearDown
    request=test_travel.TravelApiTest.request
    create=test_travel.TravelApiTest.create
    decide=test_travel.TravelApiTest.decide

    def prepare(self,key='ordinary',new_copy=False):
        return self.request('POST',f'/demo-scenarios/{key}/prepare',dict(new_copy=new_copy))

    def test_catalog_three_scenarios_and_expected_amounts(self):
        items=self.request('GET','/demo-scenarios')['scenarios']
        self.assertEqual([s['id'] for s in items],['ordinary','training','anomaly'])
        self.assertEqual([s['expected']['total'] for s in items],[342600,221600,None])
        self.assertTrue(all(s['existing_case_id'] is None for s in items))

    def test_ordinary_uses_actual_calculator_and_original_links(self):
        c=self.prepare();r=c['calculation']['result']
        self.assertEqual(r['estimated_total'],342600);self.assertTrue(c['demo_report']['passed'])
        self.assertEqual(c['data_origin'],'synthetic_demo');self.assertIsNone(r['payable_amount'])
        self.assertEqual(len(c['documents']),3)
        self.assertTrue(all(t['document_ids'] and t['included'] and not t['official_verification'] for t in c['review']['transactions']))
        self.assertTrue(all(d['extraction']['engine']=='synthetic_fixture' for d in c['documents']))
        rows=self.request('GET',f"/cases/{c['id']}/drafts")['drafts']
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]['is_current'])
        self.assertEqual(c['prepared_draft_id'],rows[0]['id'])

    def test_training_golden_amount_and_boundary_day_rule(self):
        c=self.prepare('training')
        self.assertEqual(c['calculation']['result']['estimated_total'],221600)
        self.assertEqual(next(x['amount'] for x in c['calculation']['result']['lines'] if x['key']=='daily'),50000)
        self.assertTrue(c['demo_report']['passed']);self.assertEqual(len(c['documents']),2)

    def test_anomalies_block_instead_of_showing_final_amount(self):
        c=self.prepare('anomaly');r=c['calculation']['result']
        self.assertEqual(r['status'],'blocked');self.assertIsNone(r['estimated_total']);self.assertTrue(c['demo_report']['passed'])
        self.assertEqual(len(c['parse_issues']),1);self.assertEqual(len(c['review']['transactions']),4)
        self.assertEqual(c['review']['candidate_total'],0)
        event=next(e for e in c['events'] if e['event_type']=='DEMO_PREPARED')
        self.assertEqual(event['payload']['duplicates_skipped'],1)
        for t in c['review']['transactions']:
            if t['cancelled']:self.decide(c,index=c['review']['transactions'].index(t),status=422)

    def test_existing_demo_reused_without_resetting_user_edits(self):
        c=self.prepare();changed=self.decide(c,decision='exclude')
        again=self.prepare()
        self.assertEqual(again['id'],c['id']);self.assertTrue(again['scenario_reused'])
        self.assertEqual(again['prepared_draft_id'],c['prepared_draft_id'])
        self.assertEqual(again['version'],changed['version']);self.assertTrue(again['calculation']['stale'])
        self.assertFalse(again['demo_report']['passed'])
        self.assertEqual(len(self.request('GET','/cases')),1)

    def test_explicit_new_copy_separate_and_catalog_points_to_latest(self):
        first=self.prepare();second=self.prepare(new_copy=True)
        self.assertNotEqual(first['id'],second['id']);self.assertFalse(second['scenario_reused'])
        self.assertEqual(len(self.request('GET','/cases')),2)
        catalog=self.request('GET','/demo-scenarios')['scenarios']
        self.assertEqual(catalog[0]['existing_case_id'],second['id'])

    def test_existing_user_case_unchanged(self):
        original=self.create();before=self.request('GET',f"/cases/{original['id']}")
        self.prepare();self.prepare('training');self.prepare('anomaly')
        self.assertEqual(before,self.request('GET',f"/cases/{original['id']}"))
        self.assertEqual(before['data_origin'],'user_input');self.assertNotIn('demo_report',before)

    def test_synthetic_markers_in_print_csv_json_and_zip(self):
        c=self.prepare();draft=self.request('GET',f"/cases/{c['id']}/drafts")['drafts'][0]
        page=self.client.get(draft['print_url']).text
        self.assertIn('합성 시연자료',page)
        csv=self.client.get(draft['csv_url']).content.decode('utf-8-sig')
        self.assertIn('합성 시연자료',csv.splitlines()[0])
        data=self.client.get(draft['json_url']).json()
        self.assertIn('합성 시연자료',data['notice']);self.assertEqual(data['snapshot']['data_origin'],'synthetic_demo')
        response=self.client.get(f"/api/travel/drafts/{draft['id']}/package")
        self.assertEqual(response.status_code,200)
        z=zipfile.ZipFile(io.BytesIO(response.content));m=json.loads(z.read('manifest.json'))
        self.assertEqual(m['data_origin'],'synthetic_demo');self.assertIn('합성',m['notice'])
        self.assertIn('합성 시연자료',z.read('00_먼저_읽어주세요.txt').decode('utf-8-sig'))
        self.assertEqual(len(m['documents']),3)
        for f in m['files']:self.assertEqual(hashlib.sha256(z.read(f['path'])).hexdigest(),f['sha256'])

    def test_failure_during_calculation_rolls_back_entire_seed(self):
        with patch.object(travel_api.calculator,'calculate',side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):self.prepare()
        self.assertEqual(self.request('GET','/cases'),[])
        with travel_api.db() as c:
            for table in ('travel_case_origins','travel_documents','travel_transactions','travel_drafts','travel_events'):
                self.assertEqual(c.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_missing_fixture_no_partial_case(self):
        with patch.object(travel_api.travel_demo,'fixture_bytes',side_effect=OSError('missing')):
            self.request('POST','/demo-scenarios/ordinary/prepare',dict(new_copy=False),409)
        self.assertEqual(self.request('GET','/cases'),[])

    def test_unknown_scenario_and_extra_inputs_rejected(self):
        self.request('POST','/demo-scenarios/missing/prepare',dict(new_copy=False),404)
        self.request('POST','/demo-scenarios/ordinary/prepare',dict(organization_id='demo-city'),422)
        self.assertEqual(self.request('GET','/cases'),[])


if __name__=='__main__':unittest.main()
