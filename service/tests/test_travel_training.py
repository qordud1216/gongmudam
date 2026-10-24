"""별표의 합숙/비합숙 차이, 기관 청구액, 시행일과 기존 사본을 검증한다."""
import json
import unittest
from unittest.mock import patch
from app import travel_calculator as calculator
import test_travel


class TrainingTest(unittest.TestCase):
    setUp=test_travel.TravelApiTest.setUp
    tearDown=test_travel.TravelApiTest.tearDown
    request=test_travel.TravelApiTest.request
    create=test_travel.TravelApiTest.create
    evidence=test_travel.TravelApiTest.evidence
    decide=test_travel.TravelApiTest.decide

    def prepared(self,org='national-general',hotel=False,**changes):
        c=self.create(organization_id=org,**changes)
        c=self.evidence(c,'10/15 08:00 코레일 52,300원\n10/17 17:00 코레일 52,300원'+('\n10/15 20:00 호텔 160,000원' if hotel else ''))
        for i in range(len(c['review']['transactions'])): c=self.decide(c,index=i)
        return c

    def calculate(self,c,training=None,**changes):
        t=dict(entry_date='2026-10-15',completion_date='2026-10-17',teaching_dates=['2026-10-15','2026-10-16','2026-10-17'],residential=True,dorm_available=True,notice_reference='합성 교육운영과-1234',notice_confirmed=True,costs_confirmed=True,institution_lodging=40000,institution_meal=27000)
        t.update(training or {})
        v=dict(version=c['version'],grade='group2',conditions_confirmed=True,ordinary_fare_confirmed=True,training=t)
        v.update(changes)
        return self.request('POST',f"/cases/{c['id']}/calculate",v)

    def codes(self,c): return [b['code'] for b in c['calculation']['result']['blockers']]

    def test_residential_national_and_local_golden(self):
        for org,prefix in [('national-general','NT'),('gg-province','LT')]:
            with self.subTest(org=org):
                c=self.calculate(self.prepared(org))
                r=c['calculation']['result']
                self.assertEqual(r['estimated_total'],221600)
                self.assertEqual({l['key']:l['amount'] for l in r['lines']},dict(transport=104600,daily=50000,meal=27000,lodging=40000))
                self.assertEqual(r['training_summary']['other_teaching_days'],1)
                self.assertTrue(all(any(b['id']==prefix+'_TABLE' for b in l['basis']) for l in r['lines']))
                self.assertIsNone(r['payable_amount'])

    def test_nonresidential_half_other_day_actual_lunch_amount(self):
        c=self.prepared(hotel=True)
        c=self.calculate(c,dict(residential=False,dorm_available=False,institution_lodging=0,institution_meal=0,lunch_deduction=18000),lodging_scope_confirmed=True,lodging_nights=[dict(night='2026-10-15',region='metropolitan'),dict(night='2026-10-16',region='metropolitan')])
        self.assertEqual(c['calculation']['result']['estimated_total'],384100)
        self.assertEqual({l['key']:l['amount'] for l in c['calculation']['result']['lines']},dict(transport=104600,daily=62500,meal=57000,lodging=160000))

    def test_local_residential_no_fare(self):
        c=self.create(organization_id='gg-province')
        c=self.calculate(c,travel_scope='inside')
        self.assertEqual(c['calculation']['result']['estimated_total'],117000)

    def test_local_nonresidential_institution_meal(self):
        c=self.create(organization_id='gg-province',overnight=False)
        c=self.calculate(c,dict(residential=False,dorm_available=False,institution_lodging=0,institution_meal=21000),travel_scope='inside')
        self.assertEqual(c['calculation']['result']['estimated_total'],83500)

    def test_single_day_boundary_counted_once(self):
        c=self.create(organization_id='gg-province',end_date='2026-10-15',overnight=False)
        c=self.calculate(c,dict(completion_date='2026-10-15',teaching_dates=['2026-10-15'],residential=False,dorm_available=False,institution_lodging=0,institution_meal=7000),travel_scope='inside')
        self.assertEqual(c['calculation']['result']['estimated_total'],32000)

    def test_all_costs_not_incurred_zero(self):
        c=self.create(organization_id='national-general')
        c=self.calculate(c,dict(institution_lodging=0,institution_meal=0,zero_items=['transport','daily','meal','lodging']))
        self.assertEqual(c['calculation']['result']['estimated_total'],0)
        draft=self.request('POST',f"/cases/{c['id']}/drafts",{'version':c['version']},201)
        self.assertIn('0원',self.client.get(draft['json_url']+'/print').text)

    def test_fire_does_not_inherit_local_training(self):
        c=self.calculate(self.prepared('gg-fire'))
        self.assertIn('TRAINING_SCOPE',self.codes(c))

    def test_dorm_available_cannot_choose_nonresidential(self):
        c=self.calculate(self.prepared(),dict(residential=False))
        self.assertIn('TRAINING_DORM',self.codes(c))

    def test_notice_and_cost_confirmation_required(self):
        for changes,code in [(dict(notice_reference=''),'TRAINING_NOTICE'),(dict(notice_confirmed=False),'TRAINING_NOTICE'),(dict(costs_confirmed=False),'TRAINING_COSTS')]:
            c=self.calculate(self.prepared(),changes)
            self.assertIn(code,self.codes(c))

    def test_holiday_and_prepost_travel_not_generalized(self):
        for t in [dict(teaching_dates=['2026-10-15','2026-10-17']),dict(entry_date='2026-10-16'),dict(teaching_dates=['2026-10-15','2026-10-16','2026-10-18'])]:
            c=self.calculate(self.prepared(),t)
            self.assertIn('TRAINING_DAYS',self.codes(c))
            self.assertIsNone(c['calculation']['result']['estimated_total'])

    def test_actual_not_fixed_settlement(self):
        c=self.calculate(self.prepared(),dict(settlement_method='fixed'))
        self.assertIn('TRAINING_FIXED',self.codes(c))

    def test_negative_amount_and_duplicate_dates_rejected(self):
        c=self.prepared()
        for t in [dict(entry_date='2026-10-15',completion_date='2026-10-17',teaching_dates=['2026-10-15'],institution_meal=-1),dict(entry_date='2026-10-15',completion_date='2026-10-17',teaching_dates=['2026-10-15']*2)]:
            self.request('POST',f"/cases/{c['id']}/calculate",dict(version=c['version'],training=t),422)
        self.assertEqual(self.request('GET',f"/cases/{c['id']}")['version'],c['version'])

    def test_institution_cost_not_added_to_hotel_receipt(self):
        c=self.calculate(self.prepared(hotel=True))
        self.assertIn('TRAINING_INSTITUTION',self.codes(c))

    def test_zero_claim_conflicts(self):
        for t,code in [(dict(zero_items=['transport']),'TRAINING_FARE_ZERO'),(dict(zero_items=['meal']),'TRAINING_MEAL_ZERO'),(dict(zero_items=['lodging']),'TRAINING_LODGING_ZERO')]:
            c=self.calculate(self.prepared(),t)
            self.assertIn(code,self.codes(c))

    def test_lunch_not_arbitrarily_one_third(self):
        c=self.prepared(hotel=True,meals_provided=True)
        c=self.calculate(c,dict(residential=False,dorm_available=False,institution_lodging=0,institution_meal=0))
        self.assertIn('TRAINING_MEALS_PROVIDED',self.codes(c))

    def test_deduction_cannot_exceed_meal_total(self):
        c=self.calculate(self.prepared(),dict(residential=False,dorm_available=False,institution_lodging=0,institution_meal=0,lunch_deduction=75001))
        self.assertIn('TRAINING_MEAL_LIMIT',self.codes(c))

    def test_lunch_deduction_cannot_hide_other_provided_meals(self):
        c=self.prepared(hotel=True,meals_provided=True)
        t=dict(residential=False,dorm_available=False,institution_lodging=0,institution_meal=0,lunch_deduction=18000)
        args=dict(lodging_scope_confirmed=True,lodging_nights=[dict(night='2026-10-15',region='metropolitan'),dict(night='2026-10-16',region='metropolitan')])
        c=self.calculate(c,t,**args)
        self.assertIn('TRAINING_MEALS_PROVIDED',self.codes(c))
        c=self.calculate(c,{**t,'lunch_only_provided':True},**args)
        self.assertEqual(c['calculation']['result']['estimated_total'],384100)

    def test_local_fraction_not_rounded_without_basis(self):
        c=self.create(organization_id='gg-province',overnight=False)
        c=self.calculate(c,dict(residential=False,dorm_available=False,institution_lodging=0,institution_meal=0),travel_scope='inside')
        self.assertIn('TRAINING_LOCAL_MEAL',self.codes(c))

    def test_national_before_effective_date_blocked(self):
        c=self.create(organization_id='national-general',start_date='2026-10-12',end_date='2026-10-14')
        c=self.calculate(c,dict(entry_date='2026-10-12',completion_date='2026-10-14',teaching_dates=['2026-10-12','2026-10-13','2026-10-14'],zero_items=['transport']))
        self.assertIn('TRAINING_VERSION',self.codes(c))
        self.assertFalse(any(r['effective_date']=='2026-10-15' for r in c['rule_snapshot']))

    def test_old_rulepack_never_gets_new_training(self):
        old=json.loads((calculator.BUNDLE_PATH.parent/'domestic_2026_10.json').read_text(encoding='utf-8'))
        old['bundle_sha256']='old-test-snapshot'
        with patch.object(calculator,'load_bundle',return_value=old): c=self.prepared()
        c=self.calculate(c)
        self.assertIn('TRAINING_SCOPE',self.codes(c))
        self.assertEqual(c['calculation']['result']['rulepack_version'],'2026-10-19.1')

    def test_draft_basis_and_immutable_snapshot(self):
        c=self.calculate(self.prepared())
        d=self.request('POST',f"/cases/{c['id']}/drafts",dict(version=c['version']),201)
        page=self.client.get(d['json_url']+'/print').text
        self.assertIn('221,600원',page);self.assertIn('별표 1 교육훈련여비',page)
        c=self.request('GET',f"/cases/{c['id']}")
        c=self.decide(c,index=0,decision='exclude')
        self.assertTrue(c['calculation']['stale'])
        self.assertEqual(page,self.client.get(d['json_url']+'/print').text)


if __name__=='__main__': unittest.main()
