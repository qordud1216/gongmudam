"""Home resumes actual saved work; chat links preserve the source-answer route."""
import json
from unittest.mock import patch
import unittest

from app import adhoc, folders, knowledge, main, task_intent, travel_api, workspace
from app.travel_models import TripCreate
from test_core import Base


class TaskIntentTest(unittest.TestCase):
    def test_explicit_work_requests(self):
        examples={'출장 정산 준비해줘':'travel_settlement', '여비를 계산하고 싶어':'travel_settlement',
                  '교육 희망자를 취합해줘':'education_collection', '업무 폴더 정리하고 자료를 분류해줘':'folder_organize'}
        for query,kind in examples.items():
            with self.subTest(query=query):self.assertEqual(task_intent.action(query)['kind'],kind)
        for query in ('내 결혼 연가는 며칠?', '사무용품 예산 목은?', '출장 규정이 뭐야?', '교육 희망자 선발 기준은?', '폴더 정리는 하지 말고 연가를 알려줘'):
            with self.subTest(query=query):self.assertIsNone(task_intent.action(query))

    def test_folder_start_never_uses_unrelated_procedure_or_model(self):
        with (patch.object(main.knowledge,'retrieve',side_effect=AssertionError('retrieval')),
              patch.object(main.assistant,'ask',side_effect=AssertionError('model'))):
            result=main.api_ask({'query':'업무 폴더를 정리하고 자료를 분류하고 싶어요.'})
        self.assertEqual(result['mode'],'folder_workflow')
        self.assertEqual(result['task_action']['kind'],'folder_organize')
        self.assertFalse(result['cited'])

    def test_travel_action_is_added_to_registered_source_answer(self):
        found={'hits':['hit'],'experiences':[],'excluded':[],'requires_basis':True}
        reply={'mode':'source_search','model':None,'answer':'등록 원문','notice':'','evidence':[]}
        with (patch.object(main.knowledge,'retrieve',return_value=found),
              patch.object(main.knowledge,'answer',return_value=reply),
              patch.object(main.answer_tree,'build',return_value={})):
            result=main.api_ask({'query':'출장 정산할 때 일비 계산 근거는?'})
        self.assertIsNone(result['plan'])
        self.assertEqual(result['mode'],'source_search')
        self.assertEqual(result['task_action']['kind'],'travel_settlement')

    def test_legal_folder_question_keeps_retrieval(self):
        for query in ('폴더 분류 후 파일 보존기간은?', '개인정보 파일을 분류하는 규정 근거는?',
                      '파일 정리 후 공문서 폐기 절차는?', '폴더를 분류할 때 어떤 자료를 삭제할 수 있어?',
                      '파일 분류 시 공공기록물법 제19조를 설명해줘',
                      '파일을 정리해줘. 공공기록물법 제19조에 따른 폐기 절차도 설명해줘'):
            self.assertFalse(task_intent.is_folder_start(query,task_intent.action(query)))

    def test_selected_library_keeps_source_retrieval_even_for_folder_start(self):
        found={'hits':[],'experiences':[],'excluded':[],'requires_basis':False}
        reply={'mode':'source_unavailable','model':None,'answer':'직접 근거 없음','notice':'','evidence':[]}
        with (patch.object(main.knowledge,'retrieve',return_value=found) as retrieve,
              patch.object(main.knowledge,'answer',return_value=reply),
              patch.object(main.answer_tree,'build',return_value={})):
            response=main.api_ask({'query':'폴더를 정리해줘','knowledge_library_id':'chosen'})
        retrieve.assert_called_once()
        self.assertEqual(response['mode'],'source_unavailable')


class RecentWorkTest(Base):
    def setUp(self):
        travel_api.initialize();adhoc.initialize();folders.initialize();knowledge.initialize()

    def test_empty_and_read_only_then_resume_all_three_kinds(self):
        self.assertEqual(workspace.recent(),{'items':[],'totals':{'travel':0,'collection':0,'folder':0}})
        trip=travel_api.create_case(TripCreate(organization_id='national-general',work_pattern='일반근무',
            destination='세종',purpose='합성 화면 점검',start_date='2026-10-21',end_date='2026-10-21',
            overnight=False,transport='철도',meals_provided=False))
        job=adhoc.create(adhoc.Create(situation='교육 희망자를 취합해요.',title='합성 교육 취합',course='실무교육',
            event_date='2026-11-06',deadline='2026-10-30',departments=['총무팀']))
        source=self.tmp/'synthetic-folder';source.mkdir(exist_ok=True)
        (source/'안내.txt').write_text('업무명: 화면 점검\n연도: 2026',encoding='utf-8')
        folder=folders.connect(folders.Connect(name='합성 폴더',roots=[str(source)]))
        paths=[travel_api.DB_PATH,adhoc.DB_PATH,folders.DB_PATH]
        before={path:path.read_bytes() for path in paths}
        with patch.object(workspace.httpx,'get',side_effect=AssertionError('model/server call')):
            response=workspace.recent()
        self.assertEqual(before,{path:path.read_bytes() for path in paths})
        self.assertEqual(response['totals'],{'travel':1,'collection':1,'folder':1})
        by_kind={i['kind']:i for i in response['items']}
        self.assertEqual(by_kind['travel']['href'],f"travel.html?case={trip['id']}#settle")
        self.assertEqual(by_kind['travel']['status'],'증빙 등록')
        self.assertIn('안내 확인',by_kind['education']['next_action'])
        self.assertEqual(by_kind['education']['href'],f"adhoc.html#job-{job['id']}")
        self.assertEqual(by_kind['folder']['href'],f"folders.html#{folder['id']}")
        # A completed report cannot be inferred from having a saved job.
        self.assertNotEqual('완료',by_kind['education']['status'])
        self.assertNotIn('roots',json.dumps(response))

    def test_source_count_counts_registered_enabled_records(self):
        with folders.db() as c:
            c.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?)',('k1','lib','f1',1,'{}'))
            c.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?)',('k2','lib','f2',0,'{}'))
        with patch.object(workspace.httpx,'get',side_effect=__import__('httpx').ConnectError('offline')):
            self.assertEqual(workspace.status()['resources']['knowledge_sources'],1)

    def test_workflow_changes_bring_an_old_job_into_recent_two(self):
        saved=[]
        for n in range(3):
            saved.append(adhoc.create(adhoc.Create(situation='합성 교육 명단 취합',title=f'합성 최근 업무 {n}',course='실무 교육',
                event_date='2026-11-06',deadline='2026-10-30',departments=['총무팀'])))
        with adhoc.db() as c:
            for n,job in enumerate(saved):
                c.execute('UPDATE jobs SET created_at=? WHERE id=?',(f'2026-10-{10+n:02}T00:00:00+00:00',job['id']))
                c.execute('UPDATE history SET created_at=? WHERE job_id=?',(f'2026-10-{10+n:02}T00:00:00+00:00',job['id']))
            c.execute('''INSERT INTO job_workflow_history(job_id,revision,action,detail,created_at) VALUES(?,1,'edit','{}',?)''',
                (saved[0]['id'],'2099-01-01T00:00:00+00:00'))
        items=[i for i in workspace.recent()['items'] if i['kind']=='education']
        self.assertEqual(items[0]['id'],saved[0]['id'])
        self.assertEqual(items[0]['updated_at'],'2099-01-01T00:00:00+00:00')
