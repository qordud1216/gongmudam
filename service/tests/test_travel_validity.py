"""원문 재확인 범위와 예정 출장, 기존 사건의 명시적 기준 갱신 검증."""
import copy,json,unittest
from unittest.mock import patch
from app import travel_calculator as calculator,travel_validity,travel_api,official_sources
import test_travel_calculation


class TravelValidityTest(unittest.TestCase):
    request=test_travel_calculation.LegalCalculationTest.request
    create=test_travel_calculation.LegalCalculationTest.create
    evidence=test_travel_calculation.LegalCalculationTest.evidence
    decide=test_travel_calculation.LegalCalculationTest.decide
    normal=test_travel_calculation.LegalCalculationTest.normal
    calc=test_travel_calculation.LegalCalculationTest.calc

    def setUp(self):
        test_travel_calculation.LegalCalculationTest.setUp(self)
        self.clock=patch.object(travel_validity,'today',return_value='2026-10-20');self.clock.start()
    def tearDown(self):
        self.clock.stop();test_travel_calculation.LegalCalculationTest.tearDown(self)

    def prepared_trip(self,start='2026-10-19',end='2026-10-20',org='national-general'):
        return self.normal(organization_id=org,start_date=start,end_date=end,
            text=f'{start} 08:00 코레일 100원\n{start} 20:00 합성호텔 120,000원')

    def amount(self,c,region='seoul',**kw):
        return self.calc(c,lodging_nights=[dict(night=c['trip_json']['start_date'],region=region)],**kw)

    def legacy(self):
        old=json.loads((calculator.BUNDLE_PATH.parent/'domestic_tables_2026_10.json').read_text(encoding='utf-8'))
        old['bundle_sha256']='v41-test-snapshot'
        with patch.object(calculator,'load_bundle',return_value=old):c=self.prepared_trip()
        return c

    def preview(self,c):
        return self.request('GET',f"/cases/{c['id']}/legal-pack-preview?version={c['version']}")

    def apply(self,c,p=None,**changes):
        p=p or self.preview(c)
        body=dict(version=c['version'],preview_digest=p['preview_digest'],confirmed=True,reason='재확인 원문을 대조하여 기준 갱신')
        return self.request('POST',f"/cases/{c['id']}/legal-pack-update",{**body,**changes})

    def test_completed_after_oct19_for_all_registered_profiles(self):
        for org in ('national-general','gg-province','gg-fire'):
            with self.subTest(org=org):
                r=self.amount(self.prepared_trip(org=org))['calculation']['result']
                self.assertEqual(r['estimated_total'],200100)
                self.assertEqual(r['temporal']['status'],'reviewed')
                self.assertEqual(r['temporal']['reviewed_through'],'2026-10-20')
                self.assertTrue(all(ref['verified_on']=='2026-10-20' for line in r['lines'] for ref in line['basis']))

    def test_future_period_is_estimate_and_exports_say_so(self):
        c=self.amount(self.prepared_trip('2026-10-21','2026-10-22'),region='metropolitan')
        r=c['calculation']['result']
        self.assertEqual(r['estimated_total'],180100)
        self.assertTrue(r['temporal']['is_estimate'])
        self.assertIn('사전산정',r['notice'])
        d=self.request('POST',f"/cases/{c['id']}/drafts",dict(version=c['version']),201)
        self.assertIn('예정 출장 사전산정',self.client.get(d['json_url']+'/print').text)
        self.assertIn('예정 출장 사전산정',self.client.get(d['json_url']+'/csv').content.decode('utf-8-sig'))
        package=self.request('GET',f"/drafts/{d['id']}/package-check")
        self.assertIn('FUTURE_ESTIMATE',[item['code'] for item in package['checklist']])

    def test_expired_preview_requires_recheck_does_not_auto_renew_date(self):
        c=self.prepared_trip('2026-10-21','2026-10-22')
        with patch.object(travel_validity,'today',return_value='2026-10-23'):
            c=self.amount(c);r=c['calculation']['result']
        self.assertIsNone(r['estimated_total'])
        self.assertEqual(r['temporal']['status'],'needs_recheck')
        self.assertIn('VERSION_RANGE',[b['code'] for b in r['blockers']])
        d=self.request('POST',f"/cases/{c['id']}/drafts",dict(version=c['version']),201)
        csv=self.client.get(d['json_url']+'/csv').content.decode('utf-8-sig')
        self.assertIn('적용 기준 확인 필요 · 계산 보류',csv)
        self.assertNotIn('확인 기간 내 산정',csv)

    def test_future_horizon_and_known_amendment_boundary_block(self):
        pack=calculator.select_pack('national-general')
        self.assertTrue(travel_validity.assess(pack,'2026-12-30','2026-12-31')['is_estimate'])
        self.assertFalse(travel_validity.assess(pack,'2027-01-01','2027-01-02')['allowed'])
        pack['validity_policy']['known_end_exclusive']='2026-10-21'
        self.assertFalse(travel_validity.assess(pack,'2026-10-20','2026-10-21')['allowed'])
        self.assertFalse(travel_validity.assess(pack,'2026-10-01','2026-10-20')['allowed'])

    def test_legacy_trip_stays_pinned_until_confirmed_update(self):
        c=self.amount(self.legacy())
        self.assertIsNone(c['calculation']['result']['estimated_total'])
        self.assertTrue(c['legal_update']['available'])
        d=self.request('POST',f"/cases/{c['id']}/drafts",dict(version=c['version']),201)
        old_print=self.client.get(d['json_url']+'/print').text
        p=self.preview(c)
        self.assertEqual(p['previous_verified_through'],'2026-10-19')
        self.assertEqual(p['next_verified_through'],'2026-10-20')
        self.assertTrue(p['rates_unchanged'])
        before_version=c['version'];c=self.apply(c,p)
        self.assertEqual(c['version'],before_version+1)
        self.assertTrue(c['calculation']['stale'])
        self.assertTrue(c['calculation_inputs_reset'])
        self.assertFalse(c['legal_update']['available'])
        self.assertTrue(any(e['event_type']=='LEGAL_PACK_UPDATED' for e in c['events']))
        self.assertEqual(old_print,self.client.get(d['json_url']+'/print').text)
        c=self.amount(c)
        self.assertEqual(c['calculation']['result']['estimated_total'],200100)
        self.assertFalse(c['calculation_inputs_reset'])
        with travel_api.db() as db:
            saved=db.execute('SELECT rulepack_snapshot FROM travel_calculations WHERE case_id=? ORDER BY case_version',(c['id'],)).fetchall()
            self.assertEqual([json.loads(row['rulepack_snapshot'])['version'] for row in saved],['2026-10-20.1','2026-10-20.2'])

    def test_update_confirmation_digest_and_case_conflicts_do_not_mutate(self):
        c=self.legacy();p=self.preview(c)
        path=f"/cases/{c['id']}/legal-pack-update"
        body=dict(version=c['version'],preview_digest=p['preview_digest'],confirmed=True,reason='재확인 원문을 대조하여 기준 갱신')
        self.request('POST',path,{**body,'confirmed':False},422)
        self.request('POST',path,{**body,'preview_digest':'0'*64},409)
        self.request('POST',path,{**body,'version':c['version']+1},409)
        latest=self.request('GET',f"/cases/{c['id']}")
        self.assertEqual(latest['version'],c['version'])
        self.assertEqual(latest['calculation_table']['version'],'2026-10-20.1')

    def test_rulepack_change_after_preview_is_conflict(self):
        c=self.legacy();p=self.preview(c)
        changed=copy.deepcopy(calculator.load_bundle());changed['version']='unreleased-test'
        with patch.object(calculator,'load_bundle',return_value=changed):
            self.request('POST',f"/cases/{c['id']}/legal-pack-update",dict(version=c['version'],preview_digest=p['preview_digest'],confirmed=True,reason='변경 중인 배포본 충돌 검증'),409)
        self.assertEqual(self.request('GET',f"/cases/{c['id']}")['version'],c['version'])

    def test_source_integrity_failure_blocks_update(self):
        c=self.legacy()
        with patch.object(official_sources,'metadata',return_value=None):
            self.request('GET',f"/cases/{c['id']}/legal-pack-preview?version={c['version']}",status=409)
        self.assertEqual(self.request('GET',f"/cases/{c['id']}")['version'],c['version'])

    def test_latest_and_unregistered_cases_do_not_need_upgrade(self):
        c=self.prepared_trip()
        self.assertFalse(c['legal_update']['available'])
        self.request('GET',f"/cases/{c['id']}/legal-pack-preview?version={c['version']}",status=422)
        c=self.create(organization_id='demo-city')
        self.request('GET',f"/cases/{c['id']}/legal-pack-preview?version={c['version']}",status=422)

    def test_training_after_oct19_uses_rechecked_training_sources(self):
        from app.travel_demo import definition
        for org in ('national-general','gg-province'):
            with self.subTest(org=org):
                c=self.normal(organization_id=org,start_date='2026-10-19',end_date='2026-10-20',purpose='교육',text='2026-10-19 08:00 코레일 100원')
                t=definition('training')['inputs']['training']
                t.update(entry_date='2026-10-19',completion_date='2026-10-20',teaching_dates=['2026-10-19','2026-10-20'],institution_meal=18000)
                r=self.calc(c,lodging_nights=[],training=t)['calculation']['result']
                self.assertEqual(r['estimated_total'],108100)
                self.assertFalse(r['temporal']['is_estimate'])


if __name__=='__main__':unittest.main()
