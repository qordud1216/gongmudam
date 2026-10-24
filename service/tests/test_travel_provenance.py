"""사용자 원문·검수 기록과 공식 계산의 경계 및 과거 사본 무결성 시험."""
import hashlib
import io
import json
import unittest
import zipfile
from tests import test_travel_organizations as organizations
from app import travel_api, travel_provenance


class ProvenanceTest(unittest.TestCase):
    setUp=organizations.OrganizationTest.setUp
    tearDown=organizations.OrganizationTest.tearDown
    request=organizations.OrganizationTest.request
    create=organizations.OrganizationTest.create
    org=organizations.OrganizationTest.org
    rule=organizations.OrganizationTest.rule
    diagnostic=organizations.OrganizationTest.diagnostic
    evidence=organizations.OrganizationTest.evidence
    decide=organizations.OrganizationTest.decide

    def upload(self,org,raw=None,filename='원문.txt',status=201,**metadata):
        response=self.client.post(f"/api/travel/organizations/{org['id']}/rule-sources",files={'file':(filename,raw if raw is not None else '[합성] 기관 정산 안내 원문입니다.'.encode())},data={'title':'합성 기관 정산 안내','issuer':'합성 발행기관','source_url':'https://example.org/rule',**metadata})
        self.assertEqual(response.status_code,status,response.text)
        return response.json()

    def review(self,rule,source,status=201,**changes):
        return self.request('POST',f"/rules/{rule['id']}/reviews",dict(revision=0,source_id=source['id'],location='제1항 / 1쪽',reviewer='시연 담당자',outcome='checked',note='합성 원문과 조항을 대조함',original_checked=True)|changes,status)

    def test_original_download_and_deduplication(self):
        o=self.org();source=self.upload(o)['source']
        repeated=self.upload(o,title='다르게 입력한 제목')
        self.assertTrue(repeated['duplicate'])
        self.assertEqual(repeated['source'],source)
        response=self.client.get(source['original_url'])
        self.assertEqual(response.status_code,200)
        self.assertEqual(hashlib.sha256(response.content).hexdigest(),source['sha256'])
        self.assertIn('attachment',response.headers['content-disposition'])
        self.assertEqual(response.headers['x-content-type-options'],'nosniff')

    def test_review_does_not_certify_or_enable_calculation(self):
        o=self.org();r=self.rule(o);s=self.upload(o)['source']; reviewed=self.review(r,s)
        self.assertEqual(reviewed['status'],'unverified')
        self.assertEqual(reviewed['user_review']['revision'],1)
        case=self.create(organization_id=o['id'])
        self.assertEqual(case['rule_snapshot'][0]['user_review']['source']['sha256'],s['sha256'])
        calculated=self.request('POST',f"/cases/{case['id']}/calculate",{'version':1})
        self.assertEqual(calculated['calculation']['result']['status'],'blocked')

    def test_append_history_and_optimistic_conflict(self):
        o=self.org();r=self.rule(o);s=self.upload(o)['source'];self.review(r,s)
        self.review(r,s,status=409)
        result=self.review(r,s,revision=1,outcome='needs_revision',original_checked=False,note='원문과 조항의 적용 대상을 재확인해야 함')
        self.assertEqual([v['revision'] for v in result['review_history']],[1,2])
        self.assertEqual(result['review_history'][0]['outcome'],'checked')
        self.assertTrue(any('보완 필요' in f for f in self.diagnostic(o)['findings']))

    def test_cross_org_link_and_download_are_rejected(self):
        a=self.org();b=self.org(name='다른기관');r=self.rule(a);s=self.upload(b)['source']
        self.review(r,s,status=422)
        self.request('GET',f"/organizations/{a['id']}/rule-sources/{s['id']}/original",status=404)
        self.assertEqual(self.request('GET',f"/organizations/{a['id']}/rule-sources")['sources'],[])

    def test_checked_requires_explicit_original_check(self):
        o=self.org();r=self.rule(o);s=self.upload(o)['source']
        self.review(r,s,original_checked=False,status=422)
        self.review(r,s,reviewer=' ',status=422)

    def test_official_and_mock_profiles_cannot_upload(self):
        for key in ['national-general','demo-city']:
            self.upload({'id':key},status=422)
        self.upload({'id':'missing'},status=404)

    def test_file_and_url_validation(self):
        o=self.org()
        for raw,filename in [(b'','empty.txt'),(b'\xff\xfe','bad.txt'),(b'<html>hello</html>','bad.html'),(b'text','bad.pdf'),(b'a\0b','bad.txt')]:
            self.upload(o,raw,filename,status=422)
        for url in ['javascript:alert(1)','https://user:pass@example.org/','file:///a','https://example.org/a b']:
            self.upload(o,status=422,source_url=url)
        self.upload(o,status=422,issuer=' ')

    def test_source_size_limit(self):
        self.upload(self.org(),b'x'*(travel_provenance.MAX_BYTES+1),status=422)

    def test_existing_pdf_can_be_preserved_without_text_extraction(self):
        pdf=travel_api.ROOT/'reference_data'/'travel'/'national_training_table.pdf'
        source=self.upload(self.org(),pdf.read_bytes(),'table.pdf')['source']
        self.assertEqual(source['media_type'],'application/pdf')
        self.assertGreater(source['pages'],0)

    def test_old_case_does_not_change_after_review(self):
        o=self.org();r=self.rule(o);old=self.create(organization_id=o['id']);s=self.upload(o)['source']
        self.review(r,s)
        self.assertEqual(self.request('GET',f"/cases/{old['id']}")['rule_snapshot'],old['rule_snapshot'])
        self.assertNotIn('user_review',old['rule_snapshot'][0])

    def prepared_draft(self):
        o=self.org();r=self.rule(o);s=self.upload(o)['source'];self.review(r,s)
        c=self.decide(self.evidence(self.create(organization_id=o['id']),'10/15 08:00 코레일 52,300원 승인'))
        d=self.request('POST',f"/cases/{c['id']}/drafts",{'version':c['version']},201)
        return o,r,s,c,d

    def test_package_freezes_source_and_review(self):
        o,r,s,c,d=self.prepared_draft()
        url=f"/api/travel/drafts/{d['id']}/package"
        before=self.client.get(url);self.assertEqual(before.status_code,200)
        with zipfile.ZipFile(io.BytesIO(before.content)) as z:
            manifest=json.loads(z.read('manifest.json'))
            source=manifest['rule_sources'][0]
            self.assertEqual(source['origin'],'user_registered')
            self.assertEqual(hashlib.sha256(z.read(source['archive_path'])).hexdigest(),s['sha256'])
            self.assertTrue(any(name.startswith('근거원문/') for name in z.namelist()))
        self.review(r,s,revision=1,outcome='needs_revision',note='새로운 보완 사항을 발견함')
        self.assertEqual(self.client.get(url).content,before.content)
        html=self.client.get(f"/api/travel/drafts/{d['id']}/print").text
        self.assertIn('원문 대조 완료 기록',html)
        self.assertIn('사용자 등록 원문',html)

    def test_original_corruption_blocks_download_and_package(self):
        o,r,s,c,d=self.prepared_draft()
        with travel_api.db() as connection:
            connection.execute('UPDATE travel_rule_sources SET original=? WHERE id=?',(b'corrupted',s['id']))
        self.request('GET',s['original_url'].removeprefix('/api/travel'),status=409)
        self.request('GET',f"/drafts/{d['id']}/package",status=409)
