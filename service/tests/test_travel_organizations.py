"""기관 설정의 범위 분리, 버전 충돌, 과거 출장 보존 시험."""
import unittest
from tests import test_travel


class OrganizationTest(unittest.TestCase):
    setUp=test_travel.TravelApiTest.setUp
    tearDown=test_travel.TravelApiTest.tearDown
    request=test_travel.TravelApiTest.request
    create=test_travel.TravelApiTest.create
    evidence=test_travel.TravelApiTest.evidence
    decide=test_travel.TravelApiTest.decide

    def org(self, **changes):
        return self.request('POST','/organizations',dict(name='경기도 한빛시청',region='경기도',organization_type='시 소속기관',personnel_type='지방공무원')|changes,201)

    def diagnostic(self, org, **dates):
        params={'start_date':'2026-10-15','end_date':'2026-10-17',**dates}
        return self.request('GET',f"/organizations/{org['id']}/diagnostics?"+'&'.join(k+'='+v for k,v in params.items()))

    def rule(self, org, **changes):
        return self.request('POST','/rules',dict(pack_id=org['rule_packs'][0],title='기관 정산 안내',article='제1항',text='기관의 원본 증빙을 확인한다.',effective_date='2026-10-01',version='draft1')|changes,201)

    def test_new_org_is_isolated_and_unverified(self):
        o=self.org()
        self.assertFalse(o['calculation_available'])
        self.assertEqual(o['profile_kind'],'registered')
        self.assertEqual(len(o['rule_packs']),1)
        self.assertTrue(o['rule_packs'][0].startswith('ORG_'))
        self.assertEqual(self.diagnostic(o)['rules'],[])
        case=self.create(organization_id=o['id'])
        self.assertEqual(case['rule_snapshot'],[])
        self.assertIsNone(case['legal_profile'])
        calculated=self.request('POST',f"/cases/{case['id']}/calculate",{'version':1})
        self.assertEqual(calculated['calculation']['result']['status'],'blocked')

    def test_cannot_set_official_pack_or_enable_calculation(self):
        payload=dict(name='기관',region='서울',organization_type='중앙기관',personnel_type='국가공무원')
        for key,val in [('rule_packs',['LEGAL_NATIONAL']),('calculation_available',True),('id','national-general')]:
            self.request('POST','/organizations',{**payload,key:val},422)

    def test_duplicate_registration(self):
        self.org()
        self.request('POST','/organizations',dict(name='경기도 한빛시청',region='경기도',organization_type='시 소속기관',personnel_type='지방공무원'),409)

    def test_settings_snapshot_and_stale_revision(self):
        o=self.org(); old=self.create(organization_id=o['id'])
        body=dict(revision=1,work_pattern='교대근무',required_forms=['출장명령서','기관 정산서'],note='원본 대조')
        updated=self.request('PATCH',f"/organizations/{o['id']}/settings",body)
        self.assertEqual(updated['settings_revision'],2)
        self.request('PATCH',f"/organizations/{o['id']}/settings",body,409)
        self.assertEqual(self.request('GET',f"/cases/{old['id']}")['profile_snapshot'],old['profile_snapshot'])
        new=self.create(organization_id=o['id'],work_pattern='교대근무')
        self.assertEqual(new['profile_snapshot']['settings']['required_forms'],['출장명령서','기관 정산서'])
        self.assertTrue(any('기관 정산서' in s for s in new['review']['next_actions']))

    def test_presets_cannot_be_changed(self):
        self.request('PATCH','/organizations/national-general/settings',dict(revision=1),422)

    def test_form_validation(self):
        for forms in [['중복','중복'],[' '],['x'*151]]:
            self.request('POST','/organizations',dict(name='테스트',region='경기',organization_type='기관',personnel_type='공무원',required_forms=forms),422)

    def test_org_rule_scope_and_old_snapshot(self):
        a=self.org(); b=self.org(name='다른기관')
        old=self.create(organization_id=a['id'])
        self.rule(a)
        self.assertEqual(len(self.diagnostic(a)['rules']),1)
        self.assertEqual(self.diagnostic(b)['rules'],[])
        self.assertEqual(self.request('GET',f"/cases/{old['id']}")['rule_snapshot'],[])
        self.assertEqual(len(self.create(organization_id=a['id'])['rule_snapshot']),1)

    def test_partial_period_and_overlapping_versions(self):
        o=self.org();self.rule(o,expiry_date='2026-10-16')
        self.rule(o,effective_date='2026-10-15',version='draft2')
        d=self.diagnostic(o)
        self.assertEqual(len(d['overlaps']),1)
        self.assertEqual(len(d['partial_rule_ids']),1)
        self.assertFalse(d['organization']['calculation_available'])

    def test_adjacent_versions_do_not_overlap(self):
        o=self.org();self.rule(o,expiry_date='2026-10-16')
        self.rule(o,effective_date='2026-10-16',version='draft2')
        self.assertEqual(self.diagnostic(o)['overlaps'],[])

    def test_date_and_unknown_organization_validation(self):
        o=self.org()
        self.request('GET',f"/organizations/{o['id']}/diagnostics?start_date=2026-10-18&end_date=2026-10-17",status=422)
        self.request('GET','/organizations/missing/diagnostics?start_date=2026-10-15&end_date=2026-10-17',status=404)

    def test_official_diagnostic_coverage(self):
        d=self.diagnostic({'id':'national-general'})
        self.assertTrue(d['organization']['calculation_available'])
        self.assertTrue(d['rules'])
        d=self.diagnostic({'id':'national-general'},end_date='2027-01-20')
        self.assertTrue(any('확인 범위' in f for f in d['findings']))
        d=self.diagnostic({'id':'national-general'},end_date='2026-10-20')
        self.assertFalse(any('확인 범위' in f for f in d['findings']))

    def test_bootstrap_reports_settings(self):
        o=self.org()
        found=next(r for r in self.request('GET','/bootstrap')['organizations'] if r['id']==o['id'])
        self.assertEqual(found['settings_revision'],1)
        self.assertEqual(found['profile_kind'],'registered')

    def test_registered_org_exports_and_form_checklist(self):
        o=self.org(required_forms=['기관 여비정산서'])
        c=self.create(organization_id=o['id'])
        c=self.evidence(c,'10/15 08:00 코레일 52,300원 승인')
        c=self.decide(c)
        draft=self.request('POST',f"/cases/{c['id']}/drafts",{'version':c['version']},201)
        raw=self.request('GET',f"/drafts/{draft['id']}")
        self.assertIn('기관 등록자료',raw['notice'])
        for suffix in ['print','csv']:
            r=self.client.get(f"/api/travel/drafts/{draft['id']}/{suffix}")
            self.assertEqual(r.status_code,200)
            self.assertIn('기관 등록자료',r.content.decode('utf-8-sig'))
        check=self.request('GET',f"/drafts/{draft['id']}/package-check")
        self.assertTrue(any(i['code']=='ORGANIZATION_FORM' and '기관 여비정산서' in i['message'] for i in check['checklist']))
