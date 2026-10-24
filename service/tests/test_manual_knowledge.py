import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
from app import folders,knowledge,manual_knowledge as m,main,folder_scan

def pdf_bytes(pages=23,empty=False):
    writer=PdfWriter()
    for n in range(pages):
        page=writer.add_blank_page(width=600,height=400)
        if not empty:
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
            stream=DecodedStreamObject();stream.set_data(f'BT /F1 12 Tf 20 200 Td (Unique page {n+1} manual procedure) Tj ET'.encode())
            page[NameObject('/Contents')]=stream
    target=io.BytesIO();writer.write(target);return target.getvalue()

def doc(text,page=28,title='e-사람 초과근무 매뉴얼'):
    return dict(id='m1',library_id='manuals',file_id='f1',reference_kind=m.KIND,title=title,enabled=True,current=True,
        kind='업무편람',institution='제공 매뉴얼',sha256='abc',effective_date='',limited=False,page_count=30,indexed_pages=30,
        units=[dict(text=text,page=page,loc=f'PDF {page}쪽')])

class ManualTest(unittest.TestCase):
    def test_all_pages_after_twenty_are_indexed_exactly(self):
        r=m.extract_pdf(pdf_bytes());self.assertEqual(r['page_count'],23);self.assertEqual(r['indexed_pages'],23)
        self.assertIn('Unique page 23',r['units'][-1]['text']);self.assertEqual(r['units'][-1]['page'],23)
    def test_empty_pages_reported_not_claimed_as_indexed(self):
        r=m.extract_pdf(pdf_bytes(2,empty=True));self.assertEqual(r['indexed_pages'],0);self.assertEqual(len(r['page_coverage']),2)
    def test_encrypted_pdf_rejected(self):
        w=PdfWriter();w.add_blank_page(width=10,height=10);w.encrypt('secret');b=io.BytesIO();w.write(b)
        with self.assertRaises(ValueError):m.extract_pdf(b.getvalue())
    def test_usage_routes_and_legal_amounts_stay_separate(self):
        for q in ('e-사람 포상휴가 목록이 안 나와','초과근무 사후신청 목록이 안 보여','유연근무 승인 후 취소는 어떻게 해?','e-사람 당직 엑셀 다운로드 방법'):
            self.assertEqual(m.classify(q)['kind'],'manual',q)
        for q in ('국가공무원 출장 일비 얼마야?','e-사람에서 일비 얼마 지급해?','배우자 출산휴가는 며칠이야?','물품 검수 기한은?','출장 정산 방법 알려줘'):
            self.assertIsNone(m.classify(q),q)
    def test_mixed_question_clarifies(self):
        self.assertEqual(m.classify('e-사람에서 연가 며칠이고 신청방법도 알려줘')['kind'],'mixed')

    def test_settlement_search_rejects_app_name_tip_and_chapter_index(self):
        q='e-사람 출장 정산 내역 불러오는 방법';plan=m.classify(q)
        tip=doc('근무지외 출장 신청. [신청] 버튼을 클릭한다. 스마트출장예약정산 앱을 통해서도 신청 가능하다.',title='e-사람 출장관리')
        index=doc('PART 1 출장정산 7.1 출장정산내역 보기 7.2 구분별 보기 7.4 e-사람 출장정산',title='스마트출장앱 교육')
        self.assertEqual(m.retrieve(q,[tip,index],plan),[])

    def test_settlement_control_page_precedes_generic_payment_overview(self):
        q='e-사람 출장 정산 내역 불러오는 방법';plan=m.classify(q)
        overview=doc('출장 여비 정산 내역을 수신하고 지급 요청을 확인한다. e-사람에서 출장 정산 연계 확인.',title='스마트출장앱 교육')
        control=doc('출장 정산 내역을 선택하고 [정산적용]과 [저장] 버튼을 클릭한다. [결재신청]한다.',title='e-사람 출장관리')
        result=m.retrieve(q,[overview,control],plan)
        self.assertIn('[정산적용]',result[0]['text'])
    def test_legal_obligation_and_deadline_not_routed_to_manual(self):
        for q in ('e-사람 병가 진단서 등록 의무가 있어?','e-사람 초과근무 신청 기한은 어떻게 돼?'):
            self.assertIsNone(m.classify(q))
        with patch.object(knowledge,'sources',return_value=[doc('초과근무 신청 총량 시간 부족')]):
            r=m.respond('e-사람 초과근무 신청 기한은 어떻게 돼?')
        self.assertEqual(r['knowledge']['reference_kind'],'legal');self.assertEqual(r['knowledge']['evidence'],[])
    def test_missing_sick_leave_facet_cannot_return_annual_savings(self):
        q='e-사람 병가 신청 서류는 무엇을 등록해?';self.assertIsNone(m.classify(q))
        q='e-사람 병가 서류 등록 메뉴 어디야?';p=m.classify(q)
        overview=doc('개요 공무원 개인의 근무상황 연가 공가 병가 등을 관리한다. 단위업무 연가저축예정일수 등록',title='e-사람 근무상황')
        unrelated=doc('초과근무 기간에 전일연가 병가가 있으면 신청할 수 없다.')
        self.assertEqual(m.retrieve(q,[overview,unrelated],p),[])
    def test_display_preserves_action_after_heading_and_wrapped_negative(self):
        s=doc('7.4 e-사람 출장정산\n정산내역을 선택한 후\n[정산적용]한다.\n정산에 자동으로 반영되지 않으므로 정\n산 시 다시 입력해야 한다.',title='e-사람 출장관리')
        with patch.object(knowledge,'sources',return_value=[s]):r=m.respond('e-사람 출장 정산 내역 불러오는 방법')
        text=r['knowledge']['tree']['branches'][0]['items'][0]['text']
        self.assertIn('[정산적용]한다.',text);self.assertIn('반영되지 않으므로 정\n산 시 다시 입력',text)
    def test_same_page_domain_and_action_required(self):
        source=doc('FAQ 초과근무 사후신청 목록에 표시되지 않는다. 사유를 입력해야 한다.')
        plan=m.classify('초과근무 사후신청 목록이 안 보여')
        self.assertEqual(m.retrieve(plan['query'],[source],plan)[0]['page'],28)
        source['units'][0]['text']='초과근무 집계 내역은 엑셀 다운로드한다.'
        self.assertEqual(m.retrieve(plan['query'],[source],plan),[])
    def test_disabled_changed_and_other_document_family_not_used(self):
        q='초과근무 사후신청 목록이 안 보여';p=m.classify(q)
        for key in ('enabled','current'):
            s=doc('초과근무 사후신청 목록에 표시되지 않는다.');s[key]=False;self.assertEqual(m.retrieve(q,[s],p),[])
        self.assertEqual(m.retrieve(q,[doc('포상휴가 목록에 표시되지 않는다.')],p),[])
    def test_manual_never_enters_legal_source_units(self):
        s=doc('일비는 999999원을 지급한다.')
        units,_=knowledge._source_units('일비 얼마',[s],__import__('datetime').date.today(),None)
        self.assertEqual(units,[])
    def test_exact_page_quote_and_no_model_generation(self):
        s=doc('FAQ\n초과근무 사후신청 목록에 아무것도 조회되지 않아요.\n사유를 입력하지 않으면 목록에 표시되지 않는다.')
        with patch.object(knowledge,'sources',return_value=[s]),patch.object(knowledge.llm,'get_provider') as provider:
            r=main.api_ask({'query':'초과근무 사후신청 목록이 안 보여'})
        self.assertEqual(r['mode'],'source_manual');self.assertEqual(r['knowledge']['evidence'][0]['quote'],s['units'][0]['text']);provider.assert_not_called()
    def test_unsupported_subject_does_not_fall_back_to_random_manual(self):
        with patch.object(knowledge,'sources',return_value=[doc('초과근무 신청한다.')]):
            r=main.api_ask({'query':'e-사람 급여계좌 변경 메뉴 어디야?'})
        self.assertEqual(r['mode'],'source_unavailable');self.assertEqual(r['knowledge']['evidence'],[])
    def test_explicit_manual_library_scope_is_honored(self):
        with patch.object(knowledge,'sources',return_value=[]) as source:
            r=m.respond('유연근무 취소 방법','other')
        source.assert_called_once_with('other');self.assertEqual(r['mode'],'source_unavailable')
    def test_register_copy_complete_idempotent_and_original_guards(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'manual.pdf';source.write_bytes(pdf_bytes())
            with patch.object(folders,'DB_PATH',root/'data/folders.db'):
                a=m.register_files([source]);b=m.register_files([source]);self.assertEqual(a['sources'][0]['id'],b['sources'][0]['id'])
                sources=knowledge.sources();self.assertEqual(len(sources),1);self.assertTrue(sources[0]['current']);self.assertEqual(sources[0]['indexed_pages'],23)
                self.assertTrue(Path(sources[0]['path']).is_relative_to(root/'data/manuals'));key=sources[0]['id']
                self.assertEqual(knowledge.original_manual(key).media_type,'application/pdf')
                with folders.db() as c:lib=folders.get(c,m.LIBRARY)
                with self.assertRaises(HTTPException) as e:knowledge.register(m.LIBRARY,knowledge.Register(version=lib['version'],file_ids=[sources[0]['file_id']],kind='법령·규정'))
                self.assertEqual(e.exception.status_code,422)
                with self.assertRaises(HTTPException) as e:folders.scan(m.LIBRARY,folders.Scan(version=lib['version']))
                self.assertEqual(e.exception.status_code,422)
                with patch.object(folder_scan,'allowed'),self.assertRaises(HTTPException) as e:
                    folder_scan.start(folder_scan.Start(name='매뉴얼 재분석',roots=lib['roots'],library_id=m.LIBRARY,version=lib['version']),None)
                self.assertEqual(e.exception.status_code,422)
                self.assertEqual(knowledge.sources()[0]['reference_kind'],m.KIND)
                source.unlink();self.assertTrue(knowledge.sources()[0]['current'])
                Path(sources[0]['path']).write_bytes(b'changed')
                with self.assertRaises(HTTPException) as e:knowledge.original_manual(key)
                self.assertEqual(e.exception.status_code,409)
    def test_original_invalid_or_disabled_returns_not_found(self):
        with patch.object(knowledge,'sources',return_value=[]):
            with self.assertRaises(HTTPException) as e:knowledge.original_manual('../escape')
        self.assertEqual(e.exception.status_code,404)

if __name__=='__main__':unittest.main()
