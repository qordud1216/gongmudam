"""등록 별표 연결의 독립 기대값·원문 무결성·사본 보존 검증. 합성 자료/임시 DB만 사용."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from app import official_sources, travel_calculator as calculator, travel_rates
from app.travel_models import CalculationInput
import test_travel_calculation


class RegisteredRateTableTest(unittest.TestCase):
    setUp=test_travel_calculation.LegalCalculationTest.setUp
    tearDown=test_travel_calculation.LegalCalculationTest.tearDown
    request=test_travel_calculation.LegalCalculationTest.request
    create=test_travel_calculation.LegalCalculationTest.create
    evidence=test_travel_calculation.LegalCalculationTest.evidence
    decide=test_travel_calculation.LegalCalculationTest.decide
    normal=test_travel_calculation.LegalCalculationTest.normal
    calc=test_travel_calculation.LegalCalculationTest.calc

    def test_payment_group_region_vehicle_matrix(self):
        # 2박3일, 운임100원(공용차 전일은0), 숙박실비240,000원.
        # 기대값은 계산기 함수를 재사용하지 않고 원문 표와 제16조로 독립 작성한다.
        for grade in ('group1','group2'):
            for region,group2_cap in [('seoul',200000),('metropolitan',160000),('other',140000)]:
                for vehicle,days,daily in [('none',[],75000),('partial',['2026-10-16'],62500),('all',['2026-10-15','2026-10-16','2026-10-17'],37500)]:
                    with self.subTest(grade=grade,region=region,vehicle=vehicle):
                        text='10/15 호텔 240,000원' if vehicle=='all' else '10/15 코레일 100원\n10/15 호텔 240,000원'
                        c=self.normal(transport='관용차' if vehicle=='all' else '철도',text=text)
                        c=self.calc(c,grade=grade,group1_standard_confirmed=grade=='group1',vehicle_dates=days,
                                    lodging_nights=[dict(night='2026-10-15',region=region),dict(night='2026-10-16',region=region)])
                        r=c['calculation']['result'];lines={line['key']:line for line in r['lines']}
                        lodging=240000 if grade=='group1' else group2_cap
                        self.assertEqual(r['estimated_total'],(0 if vehicle=='all' else 100)+daily+75000+lodging)
                        self.assertEqual(lines['lodging']['amount'],lodging)
                        self.assertEqual(lines['daily']['amount'],daily)
                        self.assertEqual(lines['lodging']['details']['cap_total'],None if grade=='group1' else group2_cap)
                        self.assertEqual(r['rate_snapshot']['grade'],grade)
                        for line in r['lines']:
                            ref=next(b for b in line['basis'] if b['id']=='T2_'+grade.upper())
                            self.assertEqual(ref['source_sha256'],'320ddc310256e7dc3f49c6cb0624ace2fd9c3a613f884a0525ac40039f9eed5c')
                            self.assertIsNotNone(official_sources.metadata(ref['registered_excerpt_sha256']))
                            self.assertTrue(any(b['id']=='T1' for b in line['basis']))

    def test_grade_exception_and_unconfirmed_do_not_get_total(self):
        c=self.normal()
        for grade,confirmed in [('unconfirmed',False),('group1',False)]:
            c=self.calc(c,grade=grade,group1_standard_confirmed=confirmed)
            self.assertIsNone(c['calculation']['result']['estimated_total'])
            self.assertIn('GRADE',[b['code'] for b in c['calculation']['result']['blockers']])

    def test_inside_time_boundary_both_groups_and_vehicles(self):
        for grade in ('group1','group2'):
            for minutes,car,assigned,expected in [(239,False,False,10000),(240,False,False,20000),(239,True,False,0),(240,True,False,10000),(240,True,True,0)]:
                with self.subTest(grade=grade,minutes=minutes,car=car,assigned=assigned):
                    c=self.create(organization_id='national-general',purpose='회의',start_date='2026-10-15',end_date='2026-10-15',overnight=False,transport='관용차' if car else '버스')
                    r=self.calc(c,grade=grade,travel_scope='inside',within_minutes=minutes,round_trip_km=3,
                                assigned_vehicle=assigned,vehicle_dates=['2026-10-15'] if car else [],lodging_nights=[])['calculation']['result']
                    self.assertEqual(r['estimated_total'],expected)
                    self.assertEqual([line['key'] for line in r['lines']],['within'])
                    self.assertTrue(any(ref['id']=='N18' for ref in r['lines'][0]['basis']))
                    self.assertNotIn('rate_snapshot',r)

    def test_overseas_and_group1_training_block(self):
        c=self.calc(self.normal(),journey_area='overseas')
        self.assertIn('OVERSEAS',[b['code'] for b in c['calculation']['result']['blockers']])
        self.assertIsNone(c['calculation']['result']['estimated_total'])
        from app.travel_demo import definition
        c=self.normal(purpose='교육')
        c=self.calc(c,grade='group1',group1_standard_confirmed=True,training=definition('training')['inputs']['training'])
        self.assertIn('GRADE',[b['code'] for b in c['calculation']['result']['blockers']])
        self.assertEqual(c['calculation']['result']['lines'],[])

    def test_source_missing_changed_or_table_tampered_blocks(self):
        c=self.normal();pack=calculator.select_pack('national-general')
        values=CalculationInput(version=1,grade='group2',conditions_confirmed=True).model_dump(mode='json',exclude={'version'})
        changed=copy.deepcopy(pack);changed['domestic_table']['groups']['group2']['daily']=999999
        r=calculator.calculate(c,c['review'],values,changed)
        self.assertIn('RATE_SOURCE',[b['code'] for b in r['blockers']])
        self.assertIsNone(r['estimated_total'])
        base=official_sources.BASE
        records=[row for row in json.loads((base/'manifest.json').read_text(encoding='utf-8')) if row.get('raw_file') in ('travel_annex1.pdf','travel_annex2.pdf')]
        for mutation in ('changed','missing'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as tmp:
                target=Path(tmp);(target/'excerpts').mkdir()
                (target/'manifest.json').write_text(json.dumps(records,ensure_ascii=False),encoding='utf-8')
                for row in records:
                    (target/row['raw_file']).write_bytes((base/row['raw_file']).read_bytes())
                    (target/'excerpts'/row['filename']).write_bytes((base/'excerpts'/row['filename']).read_bytes())
                if mutation=='changed':(target/'travel_annex2.pdf').write_bytes(b'changed')
                else:(target/'travel_annex2.pdf').unlink()
                with patch.object(official_sources,'BASE',target):
                    r=calculator.calculate(c,c['review'],values,pack)
                    self.assertFalse(travel_rates.table_view(pack)['available'])
                self.assertIn('RATE_SOURCE',[b['code'] for b in r['blockers']])
                self.assertEqual(r['lines'],[])
                self.assertIsNone(r['estimated_total'])

    def test_registered_table_is_authority_not_legacy_rate_fields(self):
        pack=calculator.select_pack('national-general');pack['rates'].update(daily=999999,meal_daily=999999,lodging_caps=dict(seoul=1,metropolitan=1,other=1))
        with patch.object(calculator,'load_bundle',return_value=pack):c=self.normal()
        c=self.calc(c)
        self.assertEqual(c['calculation']['result']['estimated_total'],342600)
        self.assertTrue(c['calculation_table']['registered'])

    def test_existing_saved_bundle_and_draft_keep_original_values(self):
        old=json.loads((calculator.BUNDLE_PATH.parent/'domestic_training_2026_10.json').read_text(encoding='utf-8'))
        old['bundle_sha256']='old-verified-bundle'
        with patch.object(calculator,'load_bundle',return_value=old):c=self.normal()
        c=self.calc(c)
        self.assertFalse(c['calculation_table']['registered'])
        self.assertEqual(c['calculation']['result']['rulepack_version'],'2026-10-19.2')
        draft=self.request('POST',f"/cases/{c['id']}/drafts",dict(version=c['version']),201)
        before=self.client.get(draft['json_url']+'/print').text
        c=self.calc(c,grade='group1',group1_standard_confirmed=True)
        self.assertIsNone(c['calculation']['result']['estimated_total'])
        self.assertEqual(before,self.client.get(draft['json_url']+'/print').text)
        self.assertIn('342,600원',before)
        changed=calculator.load_bundle();changed['sources']['national']['sha256']='0'*64
        with patch.object(calculator,'load_bundle',return_value=changed):
            self.assertEqual(self.client.get(draft['json_url']+'/package').status_code,200)

    def test_new_draft_package_preserves_official_annex_bytes(self):
        c=self.calc(self.normal(text='10/15 코레일 100원\n10/15 호텔 240,000원'),grade='group1',group1_standard_confirmed=True)
        draft=self.request('POST',f"/cases/{c['id']}/drafts",dict(version=c['version']),201)
        raw=self.client.get(draft['json_url']+'/package')
        self.assertEqual(raw.status_code,200,raw.text[:100] if raw.status_code!=200 else '')
        with zipfile.ZipFile(io.BytesIO(raw.content)) as archive:
            digests={hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist() if name.startswith('근거원문/')}
        for source_id in ('travel_annex1','travel_annex2'):
            src=calculator.load_bundle()['sources'][source_id]
            self.assertIn(src['sha256'],digests)
            response=self.client.get('/api/travel/legal-sources/'+source_id+'?sha256='+src['sha256'])
            self.assertEqual(hashlib.sha256(response.content).hexdigest(),src['sha256'])
        self.assertIn('390,100원',self.client.get(draft['json_url']+'/print').text)

    def test_unknown_region_rejected_without_version_bump(self):
        c=self.normal()
        self.request('POST',f"/cases/{c['id']}/calculate",dict(version=c['version'],grade='group2',lodging_nights=[dict(night='2026-10-15',region='unknown')]),422)
        self.assertEqual(self.request('GET',f"/cases/{c['id']}")['version'],c['version'])


if __name__=='__main__':
    unittest.main()
