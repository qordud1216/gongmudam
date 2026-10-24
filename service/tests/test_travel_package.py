import hashlib
import io
import json
import unittest
import zipfile
from unittest.mock import patch
from app import travel_api,travel_package
import test_travel
import test_travel_files


class PackageTest(unittest.TestCase):
    setUp=test_travel.TravelApiTest.setUp
    tearDown=test_travel.TravelApiTest.tearDown
    request=test_travel.TravelApiTest.request
    create=test_travel.TravelApiTest.create
    evidence=test_travel.TravelApiTest.evidence
    decide=test_travel.TravelApiTest.decide
    upload=test_travel_files.ReceiptTest.upload
    confirm=test_travel_files.ReceiptTest.confirm

    def draft(self,c):return self.request('POST',f"/cases/{c['id']}/drafts",dict(version=c['version']),201)

    def bundle(self,d):
        r=self.client.get(d['package_url']);self.assertEqual(r.status_code,200,r.text if r.status_code!=200 else '')
        self.assertEqual(r.headers['content-type'],'application/zip')
        z=zipfile.ZipFile(io.BytesIO(r.content));return r.content,z,json.loads(z.read('manifest.json'))

    def prepared(self):
        c=self.create(organization_id='national-general',purpose='회의',end_date='2026-10-15',overnight=False)
        c=self.confirm(self.upload(c));c=self.decide(c)
        c=self.request('POST',f"/cases/{c['id']}/calculate",dict(version=c['version'],grade='group2',conditions_confirmed=True,ordinary_fare_confirmed=True))
        return c

    def test_bundle_contains_draft_original_rule_copies_and_hashes(self):
        d=self.draft(self.prepared());raw,z,m=self.bundle(d)
        self.assertIn('01_정산서_초안.html',z.namelist())
        self.assertEqual(z.read('영수증/001.pdf'),test_travel_files.PDF)
        self.assertTrue(any(p.startswith('근거원문/') for p in z.namelist()))
        self.assertTrue(any(p.endswith('.html.txt') for p in z.namelist()))
        for f in m['files']:
            self.assertEqual(hashlib.sha256(z.read(f['path'])).hexdigest(),f['sha256'])
            self.assertEqual(len(z.read(f['path'])),f['size'])
        self.assertFalse(m['manifest_self_hash_included']);self.assertIsNone(m['payable_amount'])
        self.assertEqual(m['status'],'담당자 검토 준비')
        self.assertEqual(m['documents'][0]['original_filename'],'영수증.pdf')
        check=self.client.get(d['package_check_url']).json()
        self.assertEqual(check['file_count'],len(z.namelist()))
        self.assertEqual(check['total_uncompressed_bytes'],sum(i.file_size for i in z.infolist()))

    def test_same_draft_produces_identical_archive(self):
        d=self.draft(self.prepared())
        first=self.client.get(d['package_url']).content
        self.assertEqual(first,self.client.get(d['package_url']).content)

    def test_later_case_edits_do_not_change_saved_package(self):
        c=self.prepared();d=self.draft(c);first=self.client.get(d['package_url']).content
        c=self.decide(c,decision='exclude')
        self.upload(c,name='new-document.pdf',raw=test_travel_files.PDF+b'\n')
        self.assertEqual(first,self.client.get(d['package_url']).content)

    def test_pending_original_marked_and_packaged_for_review(self):
        c=self.upload(self.evidence(self.create(),test_travel_files.TEXT))
        _,z,m=self.bundle(self.draft(c))
        self.assertIn('검토대기/001.pdf',z.namelist())
        self.assertEqual(m['status'],'추가 확인 필요')
        self.assertIn('DOCUMENT_UNCONFIRMED',[i['code'] for i in m['checklist']])
        self.assertIn('NO_CALCULATION',[i['code'] for i in m['checklist']])

    def test_file_excluded_original_omitted_reason_preserved(self):
        c=self.upload(self.evidence(self.create(),test_travel_files.TEXT));doc=c['documents'][0]
        c=self.request('POST',f"/cases/{c['id']}/documents/{doc['id']}/dismiss",dict(version=c['version'],reason='출장과 관계없는 자료 확인'))
        _,z,m=self.bundle(self.draft(c))
        self.assertFalse(any(p.startswith(('영수증/','검토대기/')) for p in z.namelist()))
        self.assertEqual(m['omitted_documents'][0]['id'],doc['id'])
        self.assertIn('출장과 관계없는 자료 확인',z.read('03_정산_사본.json').decode())

    def test_document_linked_to_excluded_transaction_omitted(self):
        c=self.confirm(self.upload(self.create()));c=self.decide(c,decision='exclude')
        _,z,m=self.bundle(self.draft(c))
        self.assertEqual(len(m['omitted_documents']),1)
        self.assertFalse(any(p.startswith('영수증/') for p in z.namelist()))

    def test_original_without_sms_upload_reported_missing(self):
        c=self.evidence(self.create(),test_travel_files.TEXT);c=self.decide(c)
        _,z,m=self.bundle(self.draft(c))
        self.assertIn('ORIGINAL_NOT_LINKED',[i['code'] for i in m['checklist']])
        self.assertEqual(m['status'],'추가 확인 필요')

    def test_stale_calculation_cannot_appear_ready(self):
        c=self.prepared();c=self.decide(c,decision='exclude')
        _,z,m=self.bundle(self.draft(c))
        self.assertIn('STALE_CALCULATION',[i['code'] for i in m['checklist']])
        self.assertNotIn('102,300원',z.read('01_정산서_초안.html').decode())

    def test_tampered_or_missing_original_blocks_whole_bundle(self):
        c=self.prepared();d=self.draft(c);key=c['documents'][0]['id']
        with travel_api.db() as db: db.execute('UPDATE travel_documents SET original=? WHERE id=?',(b'changed',key))
        self.assertEqual(self.client.get(d['package_url']).status_code,409)
        self.assertEqual(self.client.get(d['package_check_url']).status_code,409)

    def test_unknown_original_in_snapshot_blocks_bundle(self):
        c=self.prepared();d=self.draft(c)
        with travel_api.db() as db:
            row=db.execute('SELECT snapshot FROM travel_drafts WHERE id=?',(d['id'],)).fetchone()
            snap=json.loads(row['snapshot']);snap['documents'][0]['id']='absent'
            snap['review']['transactions'][0]['document_ids']=['absent']
            db.execute('UPDATE travel_drafts SET snapshot=? WHERE id=?',(json.dumps(snap),d['id']))
        self.assertEqual(self.client.get(d['package_url']).status_code,409)

    def test_unknown_historic_rule_copy_blocks_instead_of_using_latest(self):
        d=self.draft(self.prepared())
        # 보존된 과거 배포본을 찾는 것은 허용하되, 어느 보존본에도 없는 해시는 대체하지 않는다.
        with travel_api.db() as db:
            row=db.execute('SELECT snapshot FROM travel_drafts WHERE id=?',(d['id'],)).fetchone()
            snap=json.loads(row['snapshot'])
            rule=next(r for r in snap['rule_snapshot'] if r.get('source_sha256'))
            rule['source_sha256']='0'*64
            db.execute('UPDATE travel_drafts SET snapshot=? WHERE id=?',(json.dumps(snap),d['id']))
        self.assertEqual(self.client.get(d['package_url']).status_code,409)

    def test_archive_names_never_use_user_filename(self):
        c=self.confirm(self.upload(self.create(),name='../../evil.pdf'));c=self.decide(c)
        _,z,m=self.bundle(self.draft(c))
        self.assertIn('영수증/001.pdf',z.namelist())
        self.assertFalse(any('..' in p or p.startswith('/') or '\\' in p for p in z.namelist()))

    def test_original_inventory_escapes_spreadsheet_formulas(self):
        c=self.confirm(self.upload(self.create(),name='=1+1.pdf'));c=self.decide(c)
        _,z,m=self.bundle(self.draft(c))
        self.assertIn("'=1+1.pdf",z.read('05_증빙원본_목록.csv').decode('utf-8-sig'))

    def test_size_limit_blocks_partial_archive(self):
        d=self.draft(self.prepared())
        with patch.object(travel_package,'MAX_PACKAGE_BYTES',100):
            self.assertEqual(self.client.get(d['package_url']).status_code,409)

    def test_unknown_draft_404(self):
        self.assertEqual(self.client.get('/api/travel/drafts/no-such-draft/package').status_code,404)


if __name__=='__main__':unittest.main()
