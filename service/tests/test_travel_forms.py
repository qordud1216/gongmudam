"""기관 텍스트 서식의 범위·기간·사본·자동 채움 및 ZIP 무결성."""
import io
import json
import unittest
import zipfile
from tests import test_travel_organizations as organizations
from app import travel_api,travel_forms


class FormTest(unittest.TestCase):
    setUp=organizations.OrganizationTest.setUp
    tearDown=organizations.OrganizationTest.tearDown
    request=organizations.OrganizationTest.request
    create=organizations.OrganizationTest.create
    org=organizations.OrganizationTest.org
    diagnostic=organizations.OrganizationTest.diagnostic
    evidence=organizations.OrganizationTest.evidence
    decide=organizations.OrganizationTest.decide

    def institution(self): return self.org(required_forms=['기관 정산서'])

    def upload(self,org,raw=None,filename='정산서.txt',status=201,**changes):
        r=self.client.post(f"/api/travel/organizations/{org['id']}/form-templates",files={'file':(filename,raw if raw is not None else '{{기관명}} / {{출장지}} / {{출장기간}}\n후보 {{거래후보합계}}\n산정 {{규정산정액}}\n지급 {{최종지급액}}'.encode())},data=dict(name='기관 정산서',version='v1',effective_date='2026-10-01')|changes)
        self.assertEqual(r.status_code,status,r.text);return r.json()

    def draft(self,org,**changes):
        c=self.create(organization_id=org['id'],**changes)
        c=self.decide(self.evidence(c,'10/15 08:00 코레일 52,300원 승인'))
        return c,self.request('POST',f"/cases/{c['id']}/drafts",{'version':c['version']},201)

    def test_ready_binding_and_safe_preview(self):
        org=self.institution();self.upload(org);c,d=self.draft(org,destination='<script>alert(1)</script>')
        self.assertEqual(c['profile_snapshot']['form_bindings'][0]['status'],'ready')
        self.assertEqual(len(d['form_previews']),1)
        r=self.client.get(d['form_previews'][0]['url']);self.assertEqual(r.status_code,200)
        self.assertNotIn('<script>',r.text);self.assertIn('&lt;script&gt;',r.text)
        self.assertIn('52,300원 · 거래 후보',r.text);self.assertIn('미산정',r.text);self.assertIn('미확정',r.text)
        self.assertIn("default-src 'none'",r.headers['content-security-policy'])

    def test_required_name_and_profile_scope(self):
        o=self.org();self.upload(o,status=422)
        self.upload({'id':'national-general'},status=422)
        self.upload({'id':'missing'},status=404)

    def test_unique_version_and_original_download(self):
        o=self.institution();t=self.upload(o);self.upload(o,status=409)
        url=f"/organizations/{o['id']}/form-templates/{t['id']}/original"
        r=self.client.get('/api/travel'+url);self.assertEqual(r.status_code,200)
        self.assertIn('{{기관명}}',r.content.decode())
        other=self.org(name='다른기관')
        self.request('GET',f"/organizations/{other['id']}/form-templates/{t['id']}/original",status=404)

    def test_template_validation(self):
        o=self.institution()
        for raw,filename in [(b'no tokens','a.txt'),(b'\xff','a.txt'),(b'a\x00{{x}}','a.txt'),(b'{{unknown}}','a.txt'),(b'{{broken','a.txt'),(b'{{x}}','a.html')]:
            self.upload(o,raw,filename,status=422)
        self.upload(o,b'x'*(travel_forms.MAX_BYTES+1),status=422)

    def test_invalid_dates(self):
        self.upload(self.institution(),expiry_date='2026-10-01',status=422)

    def test_overlap_is_not_selected(self):
        o=self.institution();self.upload(o);self.upload(o,version='v2')
        c,d=self.draft(o)
        self.assertEqual(c['profile_snapshot']['form_bindings'][0]['status'],'overlap')
        self.assertEqual(d['form_previews'],[])
        checks=self.request('GET',f"/drafts/{d['id']}/package-check")
        self.assertTrue(any(i['code']=='FORM_TEMPLATE_REVIEW' for i in checks['checklist']))

    def test_partial_period_is_not_filled(self):
        o=self.institution();self.upload(o,expiry_date='2026-10-17')
        self.assertEqual(self.create(organization_id=o['id'])['profile_snapshot']['form_bindings'][0]['status'],'partial')

    def test_adjacent_versions_and_missing_template(self):
        o=self.institution()
        old=self.create(organization_id=o['id'])
        self.assertEqual(old['profile_snapshot']['form_bindings'][0]['status'],'missing')
        self.upload(o,expiry_date='2026-10-15');self.upload(o,version='v2',effective_date='2026-10-15')
        c=self.create(organization_id=o['id'])
        self.assertEqual(c['profile_snapshot']['form_bindings'][0]['template']['version'],'v2')
        self.assertEqual(self.request('GET',f"/cases/{old['id']}")['profile_snapshot'],old['profile_snapshot'])

    def test_package_contains_original_and_filled_form(self):
        o=self.institution();self.upload(o);c,d=self.draft(o)
        r=self.client.get(d['package_url']);self.assertEqual(r.status_code,200)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            self.assertIsNone(z.testzip());m=json.loads(z.read('manifest.json'));f=m['form_templates'][0]
            self.assertIn('{{기관명}}',z.read(f['original_path']).decode())
            self.assertIn(o['name'],z.read(f['preview_path']).decode())
        check=self.request('GET',f"/drafts/{d['id']}/package-check")
        self.assertEqual(check['form_previews'],d['form_previews'])

    def test_past_preview_and_package_are_fixed(self):
        o=self.institution();self.upload(o);c,d=self.draft(o)
        url=d['form_previews'][0]['url'];before=self.client.get(url).content;archive=self.client.get(d['package_url']).content
        self.upload(o,version='v2')
        self.assertEqual(self.client.get(url).content,before)
        self.assertEqual(self.client.get(d['package_url']).content,archive)

    def test_corrupted_original_is_blocked(self):
        o=self.institution();t=self.upload(o);c,d=self.draft(o)
        with travel_api.db() as connection: connection.execute('UPDATE travel_form_templates SET original=? WHERE id=?',(b'corrupt',t['id']))
        self.request('GET',f"/organizations/{o['id']}/form-templates/{t['id']}/original",status=409)
        self.request('GET',f"/drafts/{d['id']}/package",status=409)
        self.request('POST','/cases',dict(self.trip,organization_id=o['id']),status=409)
        # Preview still renders the frozen template copy; it does not claim to reverify original bytes.
        self.assertEqual(self.client.get(d['form_previews'][0]['url']).status_code,200)

    def test_unrelated_template_cannot_be_previewed(self):
        o=self.institution();self.upload(o);c,d=self.draft(o)
        self.request('GET',f"/drafts/{d['id']}/forms/missing",status=404)

    def test_user_data_is_not_recursive_template_code(self):
        o=self.institution();self.upload(o)
        c,d=self.draft(o,destination='{{최종지급액}}')
        html=self.client.get(d['form_previews'][0]['url']).text
        self.assertIn('{{최종지급액}}',html)

    def test_stale_and_blocked_calculation_never_yield_amount(self):
        b={'template_text':'{{규정산정액}} / {{최종지급액}}'}
        o=self.institution();snapshot=self.create(organization_id=o['id'])
        snapshot['calculation']={'stale':True,'result':{'estimated_total':100000,'status':'calculated_for_review'}}
        self.assertIn('재계산 필요',travel_forms.fill(b,snapshot));self.assertNotIn('100,000',travel_forms.fill(b,snapshot))
        snapshot['calculation']['stale']=False;snapshot['calculation']['result']['status']='blocked'
        self.assertIn('보류',travel_forms.fill(b,snapshot));self.assertNotIn('100,000',travel_forms.fill(b,snapshot))
