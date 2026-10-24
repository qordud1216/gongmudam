import copy
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from fastapi.testclient import TestClient

from app import adhoc, adhoc_workflow as workflow, workflow_chat as chat, main
from tests import test_adhoc as base


class WorkflowChatTest(unittest.TestCase):
    req=base.AdhocTest.req
    create=base.AdhocTest.create
    row=base.AdhocTest.row
    upload=base.AdhocTest.upload
    decide=base.AdhocTest.decide
    empty=base.AdhocTest.empty
    clean=base.AdhocTest.clean
    ready=base.AdhocTest.ready

    def setUp(self):
        base.AdhocTest.setUp(self)
        self.catalog_patch=patch.object(workflow,'catalog',return_value=[])
        self.catalog=self.catalog_patch.start()

    def tearDown(self):
        self.catalog_patch.stop()
        base.AdhocTest.tearDown(self)

    def read(self,j):return self.req('GET',f"/jobs/{j['id']}")

    def command(self,j,action,**data):
        return self.req('PATCH',f"/jobs/{j['id']}/workflow",dict(action=action,revision=j['workflow']['revision'],data_version=j['version'],**data))

    def ask(self,query,j=None,**extra):
        body={'query':query,'workflow_request_id':str(uuid.uuid4())}
        if j:body.update(education_job_id=j['id'],workflow_revision=j['workflow']['revision'],workflow_data_version=j['version'])
        body.update(extra)
        with patch.object(main.knowledge,'retrieve',side_effect=AssertionError('edit must not retrieve law')),patch.object(main.assistant,'ask',side_effect=AssertionError('edit must not call model')):
            result=main.api_ask(body)
        self.assertEqual(result['mode'],'workflow_edit')
        return result

    def test_add_after_review_uses_real_stage_id_and_preserves_data_version(self):
        j=self.create()
        result=self.ask('검토 다음에 부서장 확인 단계를 넣어줘',j)
        after=self.read(j)
        self.assertEqual([s['title'] for s in after['workflow']['steps']],['안내 확인','희망자 모집','회신 취합','누락·중복 검토','부서장 확인','명단·결과보고'])
        self.assertEqual(after['version'],j['version'])
        self.assertEqual(after['workflow']['revision'],1)
        self.assertEqual(result['workflow_chat']['status'],'applied')
        self.assertTrue(all(s['completed_at'] is None for s in after['workflow']['steps']))
        audit=after['workflow']['history'][0]['detail']
        self.assertEqual(audit['source'],'chat');self.assertEqual(audit['request_text'],result['query'])

    def test_existing_stage_is_moved_or_unchanged_without_duplicates(self):
        j=self.command(self.create(),'add',title='부서장 확인')
        original=j['workflow']['steps'][-1]['id']
        result=self.ask('검토 다음에 부서장 확인 단계를 넣어줘',j)
        current=self.read(j)
        self.assertEqual(current['workflow']['steps'][-2]['id'],original)
        self.assertEqual(len(current['workflow']['steps']),6)
        self.assertEqual(result['workflow_chat']['status'],'applied')
        result=self.ask('검토 다음에 부서장 확인 단계를 넣어줘',current)
        self.assertEqual(result['workflow_chat']['status'],'unchanged')
        self.assertEqual(current,self.read(j))

    def test_edit_title_detail_caution_and_manual_checks(self):
        j=self.command(self.create(),'add',title='부서장 확인')
        requests=[('부서장 확인 이름을 최종 확인으로 바꿔줘','title','최종 확인'),
                  ('최종 확인 설명을 "명단 원본과 대조해요"로 바꿔줘','detail','명단 원본과 대조해요'),
                  ('최종 확인 주의점을 "동명이인도 확인해요"로 바꿔줘','caution','동명이인도 확인해요'),
                  ('최종 확인 완료 확인사항을 "명단 확인;누락 확인"으로 바꿔줘','checks',['명단 확인','누락 확인'])]
        for query,field,value in requests:
            with self.subTest(field=field):
                self.ask(query,j);j=self.read(j)
                self.assertEqual(j['workflow']['steps'][-1][field],value)

    def test_saved_names_containing_grammar_words_are_matched_as_whole_titles(self):
        j=self.command(self.create(),'add',title='회신 취합 후 검토')
        anchor=j['workflow']['steps'][-1]['id']
        self.ask('회신 취합 후 검토 다음에 부서장 확인 단계를 넣어줘',j);j=self.read(j)
        self.assertEqual(j['workflow']['steps'][-2]['id'],anchor)
        self.assertEqual(j['workflow']['steps'][-1]['title'],'부서장 확인')
        j=self.command(j,'add',title='누락·중복 검토 내용 확인')
        target=j['workflow']['steps'][-1]['id'];original=j['workflow']['steps'][3]['detail']
        self.ask('누락·중복 검토 내용 확인 설명을 원본 대조로 바꿔줘',j);j=self.read(j)
        self.assertEqual(j['workflow']['steps'][-1]['id'],target)
        self.assertEqual(j['workflow']['steps'][-1]['detail'],'원본 대조')
        self.assertEqual(j['workflow']['steps'][3]['detail'],original)
        self.ask('"누락·중복 검토 내용 확인" 이름을 "회신 취합 최종 확인"으로 바꿔줘',j);j=self.read(j)
        self.assertEqual(j['workflow']['steps'][-1]['title'],'회신 취합 최종 확인')

    def test_quoted_replacement_text_is_literal_even_with_legal_or_action_words(self):
        j=self.create()
        for value in ['근거 법령을 확인했어요','법적 근거를 확인해요','어떻게 확인했는지 기록하세요','표를 추가해줘 그리고 이름을 바꿔줘']:
            query=f'검토 설명을 "{value}"로 바꿔줘'
            self.ask(query,j);j=self.read(j)
            self.assertEqual(j['workflow']['steps'][3]['detail'],value)

    def test_literal_stage_suffix_or_numeric_name_is_not_reinterpreted_as_grammar(self):
        j=self.command(self.create(),'add',title='안내 확인 단계')
        target=j['workflow']['steps'][-1]['id'];original=j['workflow']['steps'][0]['detail']
        self.ask('"안내 확인 단계" 설명을 원본 대조로 바꿔줘',j);j=self.read(j)
        self.assertEqual(j['workflow']['steps'][-1]['id'],target)
        self.assertEqual(j['workflow']['steps'][-1]['detail'],'원본 대조')
        self.assertEqual(j['workflow']['steps'][0]['detail'],original)
        self.ask('안내 확인 단계 설명을 회신 원본 대조로 바꿔줘',j);j=self.read(j)
        self.assertEqual(j['workflow']['steps'][-1]['detail'],'회신 원본 대조')
        j=self.command(j,'add',title='2')
        target=j['workflow']['steps'][-1]['id'];request=j['workflow']['steps'][1]['detail']
        self.ask('"2" 단계 설명을 담당자 대조로 바꿔줘',j);j=self.read(j)
        self.assertEqual(j['workflow']['steps'][-1]['id'],target)
        self.assertEqual(j['workflow']['steps'][-1]['detail'],'담당자 대조')
        self.assertEqual(j['workflow']['steps'][1]['detail'],request)

    def test_stage_names_that_are_grammar_words_do_not_hide_actual_command_words(self):
        j=self.create()
        for title in ['다음','설명','검토 다음','1']:
            j=self.command(j,'add',title=title)
        result=self.ask('검토 다음에 부서장 확인 단계를 넣어줘',j)
        self.assertEqual(result['workflow_chat']['status'],'choose_step')
        self.assertEqual(j,self.read(j))
        self.ask('검토 다음에 부서장 확인 단계를 넣어줘',j,
                 workflow_request_id=result['workflow_chat']['request_id'],workflow_selection={'anchor':'review'});j=self.read(j)
        self.assertEqual(j['workflow']['steps'][4]['title'],'부서장 확인')
        self.assertEqual(len(j['workflow']['steps']),10)
        for value in ['원본 확인','기관 지침 확인']:
            self.ask(f'누락·중복 검토 설명을 "{value}"로 바꿔줘',j);j=self.read(j)
            self.assertEqual(j['workflow']['steps'][3]['detail'],value)

    def test_move_before_first_last_and_position(self):
        j=self.command(self.create(),'add',title='부서장 확인');target=j['workflow']['steps'][-1]['id']
        for query,index in [('부서장 확인을 검토 앞으로 옮겨줘',3),('부서장 확인 단계를 맨 앞으로 옮겨줘',0),('부서장 확인을 마지막으로 옮겨줘',5),('부서장 확인을 2번째로 옮겨줘',1)]:
            with self.subTest(query=query):
                self.ask(query,j);j=self.read(j)
                self.assertEqual(j['workflow']['steps'][index]['id'],target)

    def test_first_last_add_and_stage_number_use_current_saved_order(self):
        j=self.create()
        self.ask('맨 앞에 일정 확인 단계를 추가해줘',j);j=self.read(j)
        self.assertEqual(j['workflow']['steps'][0]['title'],'일정 확인')
        self.ask('마지막에 보관 단계를 넣어줘',j);j=self.read(j)
        self.assertEqual(j['workflow']['steps'][-1]['title'],'보관')
        self.ask('2단계 바로 다음에 연락처 확인 단계를 추가해줘',j);j=self.read(j)
        self.assertEqual(j['workflow']['steps'][2]['title'],'연락처 확인')

    def test_completed_stage_edit_keeps_identity_references_export_and_marks_review(self):
        ref=dict(origin='knowledge',id='reference',unit=0,sha256='a'*64,title='합성 확인 안내',kind='참고자료',loc='1행',text='확인 순서',href='folders.html#test',source_url='',official=False)
        self.catalog.return_value=[ref]
        j=self.ready();j=self.req('POST',f"/jobs/{j['id']}/finalize",{'version':j['version']},201)
        j=self.command(j,'add',title='부서장 확인',references=[{k:ref[k] for k in ('origin','id','unit','sha256')}])
        target=j['workflow']['steps'][-1]['id'];j=self.command(j,'complete',step_id=target,confirmed=True)
        saved=copy.deepcopy(j['workflow']['steps'][-1]);export=j['exports'][0]
        self.ask('부서장 확인 이름을 최종 확인으로 바꿔줘',j)
        result=self.read(j);step=next(s for s in result['workflow']['steps'] if s['id']==target)
        self.assertEqual(step['completed_at'],saved['completed_at']);self.assertEqual(step['references'],saved['references'])
        self.assertEqual(step['status'],'needs_review');self.assertEqual(result['exports'][0],export)
        self.assertEqual(result['version'],j['version'])

    def test_multiple_jobs_require_explicit_selection(self):
        a=self.create(title='교육 A');b=self.create(title='교육 B')
        query='검토 다음에 부서장 확인 단계를 넣어줘'
        result=self.ask(query)
        self.assertEqual(result['workflow_chat']['status'],'choose_job')
        self.assertEqual(len(result['workflow_chat']['candidates']),2)
        self.assertEqual(a,self.read(a));self.assertEqual(b,self.read(b))
        self.ask(query,a,workflow_request_id=result['workflow_chat']['request_id'])
        self.assertEqual(len(self.read(a)['workflow']['steps']),6)
        self.assertEqual(b,self.read(b))

    def test_only_job_can_be_resolved_without_guessing_latest(self):
        j=self.create();result=self.ask('검토 다음에 부서장 확인 단계를 넣어줘')
        self.assertEqual(result['workflow_chat']['job']['id'],j['id'])
        self.assertEqual(result['workflow_chat']['status'],'applied')

    def test_ambiguous_anchor_selects_one_saved_step(self):
        j=self.command(self.create(),'add',title='1차 검토');j=self.command(j,'add',title='2차 검토')
        query='검토 다음에 부서장 확인 단계를 넣어줘';result=self.ask(query,j)
        w=result['workflow_chat'];self.assertEqual(w['status'],'choose_step');self.assertEqual(w['role'],'anchor')
        self.assertEqual(len(w['choices']),3);self.assertEqual(j,self.read(j))
        anchor=next(s['id'] for s in j['workflow']['steps'] if s['title']=='2차 검토')
        result=self.ask(query,j,workflow_request_id=w['request_id'],workflow_selection={'anchor':anchor})
        after=self.read(j)['workflow']['steps']
        self.assertEqual(after[-2]['id'],anchor);self.assertEqual(after[-1]['title'],'부서장 확인')
        self.assertEqual(result['workflow_chat']['status'],'applied')

    def test_duplicate_existing_titles_require_choice_and_preserve_selected_id(self):
        j=self.command(self.create(),'add',title='부서장 확인');first=j['workflow']['steps'][-1]['id']
        j=self.command(j,'add',title='부서장 확인');second=j['workflow']['steps'][-1]['id']
        result=self.ask('검토 다음에 부서장 확인 단계를 넣어줘',j)
        self.assertEqual(result['workflow_chat']['role'],'existing')
        self.ask(result['query'],j,workflow_request_id=result['workflow_chat']['request_id'],workflow_selection={'existing':second})
        after=self.read(j)['workflow']['steps'];self.assertEqual(after[4]['id'],second)
        self.assertTrue(any(s['id']==first for s in after));self.assertEqual(len(after),7)

    def test_stale_versions_or_stale_choice_do_not_apply(self):
        j=self.create();updated=self.command(j,'add',title='확인')
        result=self.ask('검토 다음에 부서장 확인 단계를 넣어줘',j)
        self.assertEqual(result['workflow_chat']['status'],'conflict');self.assertEqual(updated,self.read(j))
        result=self.ask('검토 다음에 부서장 확인 단계를 넣어줘',updated,workflow_selection={'anchor':'missing'})
        self.assertEqual(result['workflow_chat']['status'],'needs_detail');self.assertEqual(updated,self.read(j))

    def test_request_retries_are_idempotent_even_after_other_changes(self):
        j=self.create();request_id=str(uuid.uuid4());query='검토 다음에 부서장 확인 단계를 넣어줘'
        self.ask(query,j,workflow_request_id=request_id);updated=self.read(j)
        updated=self.command(updated,'add',title='추가 확인')
        result=self.ask(query,j,workflow_request_id=request_id)
        self.assertTrue(result['workflow_chat']['replayed']);self.assertEqual(updated,self.read(j))
        another=self.create(title='다른 교육')
        result=self.ask(query,another,workflow_request_id=request_id)
        self.assertEqual(result['workflow_chat']['status'],'conflict');self.assertEqual(another,self.read(another))
        result=self.ask('안내 다음에 개인정보 확인 단계를 넣어줘',updated,workflow_request_id=request_id)
        self.assertEqual(result['workflow_chat']['status'],'conflict');self.assertEqual(updated,self.read(j))

    def test_receipt_failure_rolls_back_stage_and_audit_then_allows_retry(self):
        j=self.create();request_id=str(uuid.uuid4());query='검토 다음에 부서장 확인 단계를 넣어줘'
        encode=workflow.encode
        def fail_receipt(value):
            if isinstance(value,dict) and value.get('mode')=='workflow_edit':
                raise RuntimeError('synthetic receipt storage failure')
            return encode(value)
        with patch.object(workflow,'encode',side_effect=fail_receipt):
            with self.assertRaisesRegex(RuntimeError,'synthetic receipt storage failure'):
                self.ask(query,j,workflow_request_id=request_id)
        self.assertEqual(j,self.read(j))
        with adhoc.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM workflow_chat_requests WHERE request_id=?',(request_id,)).fetchone()[0],0)
        result=self.ask(query,j,workflow_request_id=request_id);saved=self.read(j)
        self.assertEqual(result['workflow_chat']['status'],'applied')
        self.assertEqual(saved['workflow']['revision'],1)
        self.assertEqual(len(saved['workflow']['history']),1)
        replay=self.ask(query,j,workflow_request_id=request_id)
        self.assertTrue(replay['workflow_chat']['replayed']);self.assertEqual(saved,self.read(j))

    def test_simultaneous_same_request_applies_once_and_replays_once(self):
        j=self.create();request_id=str(uuid.uuid4());query='검토 다음에 부서장 확인 단계를 넣어줘'
        body=dict(education_job_id=j['id'],workflow_revision=j['workflow']['revision'],
                  workflow_data_version=j['version'],workflow_request_id=request_id)
        barrier=Barrier(2)
        def send():
            barrier.wait(timeout=10)
            return chat.handle(query,body)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(send) for _ in range(2)]
            replies=[future.result(timeout=20) for future in futures]
        self.assertTrue(all(r['workflow_chat']['status']=='applied' for r in replies))
        self.assertEqual(sum(bool(r['workflow_chat'].get('replayed')) for r in replies),1)
        saved=self.read(j)
        self.assertEqual(saved['workflow']['revision'],1)
        self.assertEqual(sum(s['title']=='부서장 확인' for s in saved['workflow']['steps']),1)
        self.assertEqual(len(saved['workflow']['history']),1)
        with adhoc.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM workflow_chat_requests WHERE request_id=?',(request_id,)).fetchone()[0],1)

    def test_unsupported_multi_action_completion_and_unknown_stage_never_mutate(self):
        j=self.create()
        for query in ['검토 다음에 확인 단계를 추가하고 모집 단계를 맨 앞으로 옮겨줘','검토 단계를 완료해줘','검토 단계를 삭제해줘','없는단계 다음에 확인 단계를 넣어줘','검토 단계를 검토 뒤로 옮겨줘','검토 이름을 '+('가'*101)+'으로 바꿔줘']:
            with self.subTest(query=query):
                result=self.ask(query,j)
                self.assertIn(result['workflow_chat']['status'],('unsupported','needs_detail'))
                self.assertEqual(j,self.read(j))

    def test_multiple_sentences_are_not_written_as_one_stage_or_description(self):
        j=self.create()
        for query in ['검토 단계 설명을 원본 대조로 바꿔줘. 모집 설명을 회신 안내로 바꿔줘',
                      '검토 다음에 부서장 확인 단계를 넣어줘 그리고 검토 다음에 확인 단계를 넣어줘']:
            result=self.ask(query,j)
            self.assertEqual(result['workflow_chat']['status'],'unsupported')
            self.assertEqual(j,self.read(j))

    def test_document_and_new_job_requests_do_not_edit_selected_workflow(self):
        j=self.create()
        body={'education_job_id':j['id']}
        for query in ['보고서에 표를 추가해줘','검토 보고서를 만들어줘','교육 희망자 요청문을 만들어줘',
                      '교육 참석 희망자 취합 업무를 만들어줘','교육 참석 희망자를 취합할 새 업무를 만들어줘']:
            with self.subTest(query=query):
                self.assertIsNone(chat.handle(query,body))
                self.assertIsNone(chat.handle(query,{}))
        for query in ['교육 참석 희망자 취합 업무를 만들어줘','교육 참석 희망자를 취합할 새 업무를 만들어줘']:
            with patch.object(main.knowledge,'retrieve',side_effect=AssertionError('new job must use start guide')):
                result=main.api_ask({'query':query,**body})
            self.assertEqual(result['mode'],'education_workflow')
            self.assertEqual(result['task_action']['kind'],'education_collection')
        self.assertEqual(j,self.read(j))

    def test_invalid_context_rejected_at_http_boundary(self):
        j=self.create();client=TestClient(main.app)
        try:
            for fields in [{'education_job_id':'invalid'}, {'workflow_request_id':'not-a-uuid'},
                           {'education_job_id':j['id'],'workflow_revision':0},
                           {'workflow_revision':0,'workflow_data_version':1},
                           {'workflow_selection':{'anchor':'review'}},
                           {'education_job_id':j['id'],'workflow_selection':{'anchor':j['id'],'job':'review'}}]:
                with self.subTest(fields=fields):
                    r=client.post('/api/ask',json={'query':'검토 다음에 부서장 확인 단계를 넣어줘',**fields})
                    self.assertEqual(r.status_code,422,r.text)
        finally:client.close()
        self.assertEqual(j,self.read(j))

    def test_receipt_and_stage_state_survive_database_reinitialization(self):
        j=self.create();request_id=str(uuid.uuid4());query='검토 다음에 부서장 확인 단계를 넣어줘'
        self.ask(query,j,workflow_request_id=request_id);saved=self.read(j)
        adhoc.initialize()
        result=self.ask(query,j,workflow_request_id=request_id)
        self.assertTrue(result['workflow_chat']['replayed'])
        self.assertEqual(saved,self.read(j))

    def test_normal_questions_and_quoted_instructions_do_not_become_edits(self):
        for query in ['출장 정산은 언제까지 하나요?','교육 참석자 모집 근거는?','"검토 다음에 확인 단계를 넣어줘"라는 말은 무슨 뜻인가요?','단계는 어떻게 수정하나요?']:
            with self.subTest(query=query):self.assertIsNone(chat.handle(query,{}))

    def test_new_title_is_literal_text_not_code(self):
        j=self.create();query='검토 다음에 "<img src=x onerror=alert(1)>" 단계를 넣어줘'
        self.ask(query,j);j=self.read(j)
        self.assertEqual(j['workflow']['steps'][4]['title'],'<img src=x onerror=alert(1)>')

    def test_new_name_collision_does_not_silently_merge_stages(self):
        j=self.create();result=self.ask('검토 이름을 안내 확인으로 바꿔줘',j)
        self.assertEqual(result['workflow_chat']['status'],'needs_detail');self.assertEqual(j,self.read(j))


if __name__=='__main__':unittest.main()
