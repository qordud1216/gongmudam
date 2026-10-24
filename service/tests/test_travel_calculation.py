"""공식 지침의 예시·경계값과 계산 사본/보류 정책을 확인한다."""
import hashlib
import json
import unittest
from unittest.mock import patch

from app import travel_calculator as calculator
import test_travel


class LegalCalculationTest(unittest.TestCase):
    setUp=test_travel.TravelApiTest.setUp
    tearDown=test_travel.TravelApiTest.tearDown
    request=test_travel.TravelApiTest.request
    create=test_travel.TravelApiTest.create
    evidence=test_travel.TravelApiTest.evidence
    decide=test_travel.TravelApiTest.decide

    def normal(self, organization_id='national-general', text=None, **changes):
        c=self.create(organization_id=organization_id,purpose=changes.pop('purpose','회의'),**changes)
        c=self.evidence(c,text or '10/15 08:14 코레일 52,300원\n10/15 20:00 호텔 88,000원\n10/17 17:00 코레일 52,300원')
        for i in range(len(c['review']['transactions'])):
            c=self.decide(c,index=i)
        return c

    def calc(self,c,**changes):
        values=dict(version=c['version'],grade='group2',conditions_confirmed=True,
                    ordinary_fare_confirmed=True,lodging_scope_confirmed=True,
                    lodging_nights=[{'night':'2026-10-15','region':'metropolitan'}, {'night':'2026-10-16','region':'metropolitan'}])
        return self.request('POST',f"/cases/{c['id']}/calculate",{**values,**changes})

    def test_standard_three_day_ordinary_trip(self):
        c=self.calc(self.normal())
        r=c['calculation']['result']
        self.assertEqual(r['estimated_total'],342600)
        self.assertIsNone(r['payable_amount'])
        self.assertEqual({x['key']:x['amount'] for x in r['lines']},dict(transport=104600,daily=75000,meal=75000,lodging=88000))
        self.assertTrue(all(line['basis'] and all(ref['url'].startswith('https://') and ref['source_sha256'] for ref in line['basis']) for line in r['lines']))

    def test_official_guide_lodging_pool_example(self):
        # 예규 제226호 본문 614쪽: 경주 67,000 + 부산 82,000 = 149,000.
        # 밤별 min으로 147,000을 지급하는 잘못된 구현을 잡는 golden case.
        c=self.normal(text='10/15 08:14 코레일 100원\n10/15 20:00 경주호텔 67,000원\n10/16 20:00 부산호텔 82,000원')
        c=self.calc(c,lodging_nights=[{'night':'2026-10-15','region':'other'},{'night':'2026-10-16','region':'metropolitan'}])
        lodging=next(l for l in c['calculation']['result']['lines'] if l['key']=='lodging')
        self.assertEqual(lodging['amount'],149000)
        self.assertEqual(lodging['details']['cap_total'],150000)
        self.assertEqual(c['calculation']['result']['estimated_total'],299100)

    def test_lodging_three_regions_and_cap(self):
        for region,cap in [('seoul',100000),('metropolitan',80000),('other',70000)]:
            with self.subTest(region=region):
                c=self.normal(text='10/15 코레일 100원\n10/15 호텔 120,000원',end_date='2026-10-16')
                r=self.calc(c,lodging_nights=[{'night':'2026-10-15','region':region}])['calculation']['result']
                line=next(x for x in r['lines'] if x['key']=='lodging')
                self.assertEqual(line['amount'],cap)
                self.assertEqual(line['details']['over_cap'],120000-cap)

    def test_partial_vehicle_days_only(self):
        r=self.calc(self.normal(),vehicle_dates=['2026-10-16'])['calculation']['result']
        self.assertEqual(next(l['amount'] for l in r['lines'] if l['key']=='daily'),62500)
        self.assertEqual(r['estimated_total'],330100)

    def test_official_vehicle_no_fare_and_half_daily(self):
        c=self.normal(transport='관용차',text='10/15 호텔 88,000원')
        r=self.calc(c,vehicle_dates=['2026-10-15','2026-10-16','2026-10-17'])['calculation']['result']
        self.assertEqual(r['estimated_total'],200500)
        self.assertEqual(next(l['amount'] for l in r['lines'] if l['key']=='transport'),0)

    def test_actual_provincial_and_fire_scope(self):
        for org in ('gg-province','gg-fire'):
            c=self.calc(self.normal(organization_id=org))
            r=c['calculation']['result']
            self.assertEqual(r['estimated_total'],342600)
            refs=r['lines'][0]['basis']
            self.assertTrue(any(ref['id']=='N29_2' for ref in refs))
            self.assertTrue(any(ref['id']=='G4' and ref['source_version']=='경기도조례 제8887호' for ref in refs))

    def test_municipal_and_mock_cannot_inherit_province(self):
        c=self.calc(self.normal(organization_id='demo-city'))
        self.assertEqual(c['calculation']['result']['blockers'][0]['code'],'NO_LEGAL_PACK')
        self.assertIsNone(c['calculation']['result']['estimated_total'])

    def test_dates_outside_verified_package(self):
        for dates in [('2026-09-28','2026-09-30'),('2027-01-20','2027-01-22')]:
            c=self.create(organization_id='national-general',purpose='회의',start_date=dates[0],end_date=dates[1])
            r=self.calc(c,lodging_nights=[])['calculation']['result']
            self.assertIn('VERSION_RANGE',[b['code'] for b in r['blockers']])
            self.assertIsNone(r['estimated_total'])

    def test_education_and_provided_meals_do_not_get_general_total(self):
        for changes,code in [(dict(purpose='교육'),'TRAINING'),(dict(meals_provided=True),'MEALS_PROVIDED')]:
            r=self.calc(self.normal(**changes))['calculation']['result']
            self.assertIn(code,[b['code'] for b in r['blockers']])
            self.assertIsNone(r['estimated_total'])
            self.assertTrue(next(b for b in r['blockers'] if b['code']==code)['basis'])

    def test_unconfirmed_conditions_grade_and_fare(self):
        c=self.normal()
        for changes,code in [(dict(conditions_confirmed=False),'CONDITIONS'),(dict(grade='group1'),'GRADE'),(dict(ordinary_fare_confirmed=False),'FARE_CLASS'),(dict(additional_review=True),'SPECIAL')]:
            c=self.calc(c,**changes)
            self.assertIn(code,[b['code'] for b in c['calculation']['result']['blockers']])

    def test_pending_and_flagged_transactions_block(self):
        c=self.create(organization_id='national-general',purpose='회의')
        c=self.evidence(c,'10/15 코레일 100원')
        c=self.calc(c)
        self.assertIn('UNRESOLVED',[b['code'] for b in c['calculation']['result']['blockers']])
        c=self.normal(text='10/18 코레일 100원\n10/15 호텔 80,000원')
        c=self.calc(c)
        self.assertIn('FLAGGED_TRANSACTION',[b['code'] for b in c['calculation']['result']['blockers']])

    def test_lodging_must_be_explicit_and_dates_valid(self):
        c=self.normal()
        for changes in [dict(lodging_scope_confirmed=False),dict(lodging_nights=[]),dict(lodging_nights=[{'night':'2026-10-17','region':'other'}]),dict(lodging_not_claimed=True)]:
            c=self.calc(c,**changes)
            self.assertIsNone(c['calculation']['result']['estimated_total'])

    def test_duplicate_nights_rejected_and_no_version_bump(self):
        c=self.normal()
        self.request('POST',f"/cases/{c['id']}/calculate",{'version':c['version'],'lodging_nights':[{'night':'2026-10-15','region':'other'}]*2},422)
        latest=self.request('GET',f"/cases/{c['id']}")
        self.assertEqual(latest['version'],c['version'])

    def test_local_four_hour_boundary_and_vehicle(self):
        for minutes,vehicle,assigned,expected in [(239,False,False,10000),(240,False,False,20000),(239,True,False,0),(240,True,False,10000),(240,False,True,0)]:
            with self.subTest(minutes=minutes,vehicle=vehicle,assigned=assigned):
                c=self.create(organization_id='national-general',purpose='회의',start_date='2026-10-15',end_date='2026-10-15',overnight=False)
                c=self.calc(c,travel_scope='inside',within_minutes=minutes,round_trip_km='10',assigned_vehicle=assigned,vehicle_dates=['2026-10-15'] if vehicle else [],lodging_nights=[])
                self.assertEqual(c['calculation']['result']['estimated_total'],expected)
                self.request('POST',f"/cases/{c['id']}/drafts",{'version':c['version']},201)

    def test_near_distance_two_km_boundary(self):
        c=self.create(organization_id='gg-province',purpose='회의',start_date='2026-10-15',end_date='2026-10-15',overnight=False)
        c=self.calc(c,travel_scope='inside',within_minutes=240,round_trip_km='2.0',lodging_nights=[])
        r=c['calculation']['result']
        self.assertIn('NEAR',[b['code'] for b in r['blockers']])
        self.assertTrue(any(ref['id']=='G_NEAR' for b in r['blockers'] for ref in b['basis']))
        c=self.calc(c,travel_scope='inside',within_minutes=240,round_trip_km='2.1',lodging_nights=[])
        self.assertEqual(c['calculation']['result']['estimated_total'],20000)

    def test_modification_stales_result_and_draft_stays_fixed(self):
        c=self.calc(self.normal())
        d=self.request('POST',f"/cases/{c['id']}/drafts",{'version':c['version']},201)
        c=self.decide(c,index=0,decision='exclude')
        self.assertTrue(c['calculation']['stale'])
        saved=self.request('GET',f"/drafts/{d['id']}")
        self.assertFalse(saved['snapshot']['calculation']['stale'])
        self.assertEqual(saved['snapshot']['calculation']['result']['estimated_total'],342600)
        page=self.client.get(d['json_url']+'/print').text
        self.assertIn('342,600원',page)
        self.assertIn('제16조제3항',page)
        csv=self.client.get(d['csv_url']).content.decode('utf-8-sig')
        self.assertIn('342600',csv)
        self.assertIn('제16조제3항',csv)

    def test_case_keeps_package_after_new_release(self):
        c=self.normal()
        changed=calculator.load_bundle()
        changed['rates']['daily']=999999
        with patch.object(calculator,'load_bundle',return_value=changed):
            c=self.calc(c)
        self.assertEqual(c['calculation']['result']['estimated_total'],342600)

    def test_user_rule_cannot_change_calculation_pack(self):
        self.request('POST','/rules',dict(pack_id='LEGAL_NATIONAL',title='수당 조작',article='제1조',text='일비를 임의 변경합니다.',effective_date='2026-10-02',version='99'),422)

    def test_source_copies_match_checksums(self):
        pack=self.request('GET','/legal-packs')
        self.assertEqual(pack['rates']['daily'],25000)
        for key,source in pack['sources'].items():
            response=self.client.get('/api/travel/legal-sources/'+key)
            self.assertEqual(response.status_code,200)
            self.assertEqual(hashlib.sha256(response.content).hexdigest(),source['sha256'])
        self.request('GET','/legal-sources/unknown',status=404)


if __name__=='__main__': unittest.main()
