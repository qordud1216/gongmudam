import hashlib
import os
import unittest
from datetime import date
from unittest.mock import Mock,patch
from app import travel_api,travel_files
import test_travel


PDF=(travel_api.ROOT/'reference_data/travel/national_training_table.pdf').read_bytes()
PNG=(travel_api.ROOT/'static/travel-sample-receipt.png').read_bytes()
TEXT='2026-10-15 08:14 코레일 52,300원 승인'


class ReceiptTest(unittest.TestCase):
    setUp=test_travel.TravelApiTest.setUp
    tearDown=test_travel.TravelApiTest.tearDown
    request=test_travel.TravelApiTest.request
    create=test_travel.TravelApiTest.create
    evidence=test_travel.TravelApiTest.evidence
    decide=test_travel.TravelApiTest.decide

    def upload(self,c,raw=PDF,name='영수증.pdf',status=201):
        r=self.client.post(f"/api/travel/cases/{c['id']}/documents",data={'version':c['version']},files={'file':(name,raw,'application/octet-stream')})
        self.assertEqual(r.status_code,status,r.text)
        return r.json()

    def confirm(self,c,text=TEXT,checked=True,status=200):
        d=c['documents'][0]
        return self.request('POST',f"/cases/{c['id']}/documents/{d['id']}/confirm",dict(version=c['version'],text=text,original_checked=checked,reason='원본과 거래일·승인금액 대조'),status)

    def test_pdf_upload_keeps_original_without_transactions(self):
        c=self.upload(self.create())
        self.assertEqual(c['version'],2);self.assertEqual(c['review']['transactions'],[])
        d=c['documents'][0]
        self.assertEqual(d['sha256'],hashlib.sha256(PDF).hexdigest())
        self.assertEqual(d['extraction']['engine'],'pypdf')
        self.assertEqual(len(d['extraction']['pages']),1)
        self.assertIsNone(d['confirmed_at']);self.assertNotIn('original',d)
        original=self.client.get(d['original_url'])
        self.assertEqual(original.content,PDF)
        self.assertIn('attachment',original.headers['content-disposition'])
        self.assertEqual(original.headers['x-content-type-options'],'nosniff')

    def test_reject_invalid_type_size_signature_and_pdf(self):
        c=self.create()
        for raw,name in [(b'<html>','fake.pdf'),(PDF,'bad.html'),(b'','empty.pdf'),(b'%PDF-garbage','broken.pdf')]:
            self.upload(c,raw,name,422)
        with patch.object(travel_files,'MAX_BYTES',16): self.upload(c,PDF,'large.pdf',422)
        self.assertEqual(self.request('GET',f"/cases/{c['id']}")['version'],c['version'])

    def test_duplicate_bytes_different_name_not_added_or_bumped(self):
        c=self.upload(self.create())
        again=self.upload(c,name='duplicate.pdf')
        self.assertTrue(again['upload_result']['duplicate'])
        self.assertEqual(again['version'],c['version']);self.assertEqual(len(again['documents']),1)

    def test_upload_stale_version_rolls_back(self):
        old=self.create();self.evidence(old,TEXT)
        self.upload(old,status=409)

    def test_original_review_required(self):
        c=self.upload(self.create())
        self.confirm(c,checked=False,status=422)
        self.confirm(c,text='금액미확인',status=422)
        self.assertEqual(self.request('GET',f"/cases/{c['id']}")['review']['transactions'],[])

    def test_confirmed_candidate_pending_and_linked(self):
        c=self.confirm(self.upload(self.create()))
        tx=c['review']['transactions'][0]
        self.assertEqual(tx['decision'],'pending');self.assertFalse(tx['official_verification'])
        self.assertEqual(tx['document_ids'],[c['documents'][0]['id']])
        self.assertEqual(c['documents'][0]['confirmed_text'],TEXT)
        self.assertEqual(c['review']['candidate_total'],0)
        self.confirm(c,status=409)

    def test_confirm_stale_version_no_partial_changes(self):
        c=self.upload(self.create());self.evidence(c,'10/16 호텔 100원')
        self.confirm(c,status=409)
        fresh=self.request('GET',f"/cases/{c['id']}")
        self.assertIsNone(fresh['documents'][0]['confirmed_at'])
        self.assertEqual(len(fresh['review']['transactions']),1)

    def test_receipt_and_sms_duplicate_link_not_sum(self):
        c=self.evidence(self.create(),TEXT);c=self.decide(c)
        c=self.confirm(self.upload(c))
        self.assertEqual(c['import_result']['inserted'],0)
        self.assertEqual(c['import_result']['duplicates_skipped'],1)
        self.assertEqual(len(c['review']['transactions']),1)
        self.assertEqual(c['review']['candidate_total'],52300)
        self.assertEqual(len(c['review']['transactions'][0]['document_ids']),1)

    def test_cancelled_receipt_cannot_be_included(self):
        c=self.confirm(self.upload(self.create()),text=TEXT.replace('승인','취소'))
        self.decide(c,status=422)

    def test_cross_case_cannot_access_original_or_confirmation(self):
        c=self.upload(self.create());other=self.create();key=c['documents'][0]['id']
        self.request('GET',f"/cases/{other['id']}/documents/{key}/original",status=404)
        self.request('POST',f"/cases/{other['id']}/documents/{key}/confirm",dict(version=other['version'],text=TEXT,original_checked=True,reason='원본 확인 완료'),404)

    def test_exclude_preserves_original_and_reason(self):
        c=self.upload(self.create());key=c['documents'][0]['id']
        c=self.request('POST',f"/cases/{c['id']}/documents/{key}/dismiss",dict(version=c['version'],reason='출장과 관계없는 자료로 확인'))
        self.assertEqual(c['review']['transactions'],[])
        self.assertEqual(c['documents'][0]['confirmed_text'],'')
        self.assertEqual(self.client.get(c['documents'][0]['original_url']).content,PDF)
        self.assertFalse(any(f['code']=='DOCUMENT_UNCONFIRMED' for f in c['review']['findings']))

    def test_unconfirmed_document_blocks_calculation_and_upload_stales(self):
        c=self.evidence(self.create(organization_id='national-general',purpose='회의',end_date='2026-10-15',overnight=False),TEXT)
        c=self.decide(c)
        body=dict(grade='group2',conditions_confirmed=True,ordinary_fare_confirmed=True)
        c=self.request('POST',f"/cases/{c['id']}/calculate",dict(version=c['version'],**body))
        self.assertEqual(c['calculation']['result']['estimated_total'],102300)
        c=self.upload(c);self.assertTrue(c['calculation']['stale'])
        c=self.request('POST',f"/cases/{c['id']}/calculate",dict(version=c['version'],**body))
        self.assertIn('DOCUMENT_UNCONFIRMED',[b['code'] for b in c['calculation']['result']['blockers']])
        c=self.confirm(c)
        c=self.request('POST',f"/cases/{c['id']}/calculate",dict(version=c['version'],**body))
        self.assertEqual(c['calculation']['result']['estimated_total'],102300)

    def test_original_checksum_mismatch_is_blocked(self):
        c=self.upload(self.create());d=c['documents'][0]
        with travel_api.db() as db: db.execute('UPDATE travel_documents SET original=? WHERE id=?',(b'tamper',d['id']))
        self.request('GET',f"/cases/{c['id']}/documents/{d['id']}/original",status=409)

    def test_draft_keeps_document_snapshot_and_prints_hash(self):
        c=self.confirm(self.upload(self.create(),name='<script>.pdf'))
        draft=self.request('POST',f"/cases/{c['id']}/drafts",dict(version=c['version']),201)
        snapshot=self.client.get(draft['json_url']).json()['snapshot']
        self.assertEqual(snapshot['documents'][0]['confirmed_text'],TEXT)
        page=self.client.get(draft['json_url']+'/print').text
        self.assertIn('&lt;script&gt;.pdf',page);self.assertNotIn('<script>',page)
        self.assertIn(hashlib.sha256(PDF).hexdigest(),page)
        self.decide(c)
        self.assertEqual(self.client.get(draft['json_url']).json()['snapshot'],snapshot)

    def test_encrypted_and_oversize_pdf_rejected(self):
        with patch.object(travel_files,'PdfReader',return_value=Mock(is_encrypted=True)):
            self.upload(self.create(),status=422)
        with patch.object(travel_files,'PdfReader',return_value=Mock(is_encrypted=False,pages=[None]*11)):
            self.upload(self.create(),status=422)

    def test_scan_pdf_manual_fallback(self):
        with patch.object(travel_files,'PdfReader',return_value=Mock(is_encrypted=False,pages=[Mock(extract_text=lambda:'')])):
            c=self.upload(self.create())
        self.assertEqual(c['documents'][0]['suggested_text'],'')
        self.assertTrue(c['documents'][0]['extraction']['warnings'])

    @unittest.skipUnless(os.name=='nt','Windows OCR 통합 확인')
    def test_real_korean_image_ocr(self):
        c=self.upload(self.create(),PNG,'합성 영수증.png')
        d=c['documents'][0]
        self.assertEqual(d['extraction']['engine'],'Windows.Media.Ocr')
        self.assertIn('52,300',d['extraction']['text'])
        self.assertIn('코레일',d['suggested_text'])
        self.assertEqual(self.client.get(d['preview_url']).content,PNG)
        self.assertEqual(c['review']['transactions'],[])


class SuggestionTest(unittest.TestCase):
    def suggest(self,text):return travel_files.suggest_transactions(text,date(2026,10,15),date(2026,10,17))[0]

    def test_labeled_receipt(self):
        result=self.suggest('상호: 코레일\n거래일: 2026-10-15 08:14\n공급가액 47,545원\n세금 4,755원\n승인금액: 52,300원')
        self.assertEqual(result,'2026-10-15 08:14 코레일 52,300원')

    def test_ambiguous_dates_or_final_amounts_not_guessed(self):
        for text in ['상호: 코레일\n2026-10-15\n2026-10-16\n합계: 100원','상호: 코레일\n2026-10-15\n합계: 100원\n결제금액: 200원','상호: 코레일\n2026-10-15\n금액 불명']:
            self.assertEqual(self.suggest(text),'')

    def test_explicit_cancel_and_negative_amount(self):
        self.assertIn('취소',self.suggest('상호: 코레일\n2026-10-15\n승인금액: 100원\n취소'))
        self.assertEqual(self.suggest('상호: 코레일\n2026-10-15\n승인금액: -100원'),'')


if __name__=='__main__':unittest.main()
