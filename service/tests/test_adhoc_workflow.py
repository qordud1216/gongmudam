import copy
import json
import unittest
from unittest.mock import patch, MagicMock

from app import adhoc, adhoc_workflow as workflow
from tests import test_adhoc as collection_tests



class WorkflowTest(unittest.TestCase):
    req=collection_tests.AdhocTest.req
    create=collection_tests.AdhocTest.create
    row=collection_tests.AdhocTest.row
    upload=collection_tests.AdhocTest.upload
    decide=collection_tests.AdhocTest.decide
    empty=collection_tests.AdhocTest.empty
    clean=collection_tests.AdhocTest.clean
    ready=collection_tests.AdhocTest.ready

    def setUp(self):
        collection_tests.AdhocTest.setUp(self)
        self.real_catalog=workflow.catalog
        self.catalog_patch=patch.object(workflow,'catalog',return_value=[])
        self.catalog=self.catalog_patch.start()

    def tearDown(self):
        self.catalog_patch.stop()
        collection_tests.AdhocTest.tearDown(self)

    def command(self,j,action,step=None,status=200,**extra):
        return self.req('PATCH',f"/jobs/{j['id']}/workflow",
                        dict(revision=j['workflow']['revision'],data_version=j['version'],action=action,step_id=step,**extra),status)

    def step(self,j,key):
        return next(s for s in j['workflow']['steps'] if s['id']==key)

    def complete(self,j,key):
        return self.command(j,'complete',key,confirmed=True)

    def test_legacy_job_read_is_repeatable_and_does_not_guess_completion(self):
        j=self.ready()
        with adhoc.db() as c:c.execute('DELETE FROM job_workflows WHERE job_id=?',(j['id'],))
        self.assertEqual(j['workflow']['revision'],0)
        self.assertEqual(j['workflow']['completed_count'],0)
        self.assertEqual(len(j['workflow']['steps']),5)
        with adhoc.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM job_workflows').fetchone()[0],0)
        self.assertEqual(j,self.req('GET',f"/jobs/{j['id']}"))

    def test_completion_requires_human_confirmation_and_server_readiness(self):
        j=self.create()
        self.command(j,'complete','intake',status=422)
        for key in ('collect','review','report'):
            with self.subTest(key=key):self.command(j,'complete',key,status=422,confirmed=True)
        result=self.complete(j,'intake')
        self.assertEqual(self.step(result,'intake')['status'],'done')
        self.assertEqual(result['version'],j['version'])
        self.assertEqual(result['workflow']['revision'],1)

    def test_finalize_and_workflow_completion_preserve_current_export(self):
        j=self.ready()
        j=self.req('POST',f"/jobs/{j['id']}/finalize",{'version':j['version']},201)
        version=j['version'];export=j['exports'][0]
        for key in ('intake','request','collect','review','report'):j=self.complete(j,key)
        self.assertEqual(j['version'],version)
        self.assertEqual(j['exports'][0],export)
        self.assertTrue(j['exports'][0]['is_current'])
        self.assertEqual(j['workflow']['completed_count'],5)
        self.assertIsNone(j['workflow']['next_step_id'])
        adhoc.initialize()
        self.assertEqual(j,self.req('GET',f"/jobs/{j['id']}"))

    def test_conflicts_are_atomic_for_both_versions(self):
        j=self.create();later=self.complete(j,'intake')
        self.command(j,'add',status=409,title='예전 진행표에서 추가')
        data_later=self.upload(later,[self.row()])
        self.command(later,'add',status=409,title='예전 명단에서 추가')
        self.assertEqual(data_later,self.req('GET',f"/jobs/{j['id']}"))

    def test_reorder_preserves_completion_and_basic_step_identity(self):
        j=self.complete(self.create(),'intake');before=self.step(j,'intake')
        j=self.command(j,'move','intake',before_id=None)
        self.assertEqual(j['workflow']['steps'][-1]['id'],'intake')
        self.assertEqual(self.step(j,'intake')['completed_at'],before['completed_at'])
        self.assertEqual(self.step(j,'intake')['status'],'done')
        self.assertEqual({s['id'] for s in j['workflow']['steps']},{'intake','request','collect','review','report'})
        self.command(j,'archive','request',status=422)

    def test_custom_stage_archive_restore_and_own_checks(self):
        j=self.command(self.create(),'add',title='부서장 확인',checks=['명단을 확인받았어요.'],before_id='report')
        custom=next(s for s in j['workflow']['steps'] if s['kind']=='custom')
        self.assertEqual(custom['checks'],['명단을 확인받았어요.'])
        j=self.complete(j,custom['id']);j=self.command(j,'archive',custom['id'])
        self.assertFalse(any(s['id']==custom['id'] for s in j['workflow']['steps']))
        self.assertEqual(j['workflow']['archived'][0]['id'],custom['id'])
        j=self.command(j,'restore',custom['id'])
        self.assertEqual(self.step(j,custom['id'])['status'],'needs_review')
        self.assertEqual(len(j['workflow']['history']),4)

    def test_edit_marks_completed_stage_for_review_but_does_not_change_export_version(self):
        j=self.ready();j=self.complete(j,'review');version=j['version']
        j=self.command(j,'edit','review',detail='원본 파일과 수정된 성명을 다시 대조해요.')
        self.assertEqual(self.step(j,'review')['status'],'needs_review')
        self.assertEqual(j['version'],version)
        j=self.complete(j,'review');self.assertEqual(self.step(j,'review')['status'],'done')
        j=self.command(j,'reopen','review');self.assertNotEqual(self.step(j,'review')['status'],'done')

    def test_changed_collection_data_requires_reconfirmation(self):
        j=self.ready();j=self.req('POST',f"/jobs/{j['id']}/finalize",{'version':j['version']},201)
        j=self.command(j,'add',title='부서장 확인');custom=j['workflow']['steps'][-1]['id']
        for key in ('intake','request','collect','review','report',custom):j=self.complete(j,key)
        prior_revision=j['workflow']['revision'];prior_time=self.step(j,'review')['completed_at']
        j=self.upload(j,[self.row(name='추가희망자')])
        self.assertEqual(j['workflow']['revision'],prior_revision)
        for key in ('collect','review','report',custom):self.assertEqual(self.step(j,key)['status'],'needs_review')
        for key in ('intake','request'):self.assertEqual(self.step(j,key)['status'],'done')
        self.assertEqual(self.step(j,'review')['completed_at'],prior_time)
        self.assertFalse(j['exports'][0]['is_current'])
        self.command(j,'complete','review',status=422,confirmed=True)

    def test_empty_reply_conflict_blocks_collection_completion(self):
        j=self.ready();j=self.upload(j,[self.row('행정팀','추가인원')],dep='행정팀')
        self.assertTrue(any(d['conflict'] for d in j['departments']))
        self.command(j,'complete','collect',status=422,confirmed=True)

    def test_reference_snapshot_change_and_missing_are_not_silently_updated(self):
        ref=dict(origin='knowledge',id='source1',unit=0,title='교육 안내',kind='기관 지침',
                 sha256='a'*64,text='교육 희망자 명단 제출 안내',loc='2쪽',href='folders.html#demo',source_url='',official=False)
        self.catalog.return_value=[copy.deepcopy(ref)]
        j=self.command(self.create(),'edit','request',references=[{k:ref[k] for k in ('origin','id','unit','sha256')}])
        j=self.complete(j,'request')
        changed=ref|{'sha256':'b'*64,'text':'변경된 교육 안내'};self.catalog.return_value=[changed]
        j=self.req('GET',f"/jobs/{j['id']}")
        s=self.step(j,'request');self.assertEqual(s['status'],'needs_review');self.assertFalse(s['can_complete'])
        self.assertEqual(s['references'][0]['text'],ref['text'])
        self.command(j,'complete','request',status=422,confirmed=True)
        j=self.command(j,'edit','request',detail='이번 업무에서 확인할 사항만 수정해요.')
        self.assertEqual(self.step(j,'request')['references'][0]['sha256'],'a'*64)
        self.command(j,'edit','request',references=[{k:ref[k] for k in ('origin','id','unit','sha256')}],status=422)
        j=self.command(j,'edit','request',references=[{k:changed[k] for k in ('origin','id','unit','sha256')}])
        self.assertTrue(self.step(j,'request')['can_complete'])
        self.catalog.return_value=[]
        self.assertFalse(self.step(self.req('GET',f"/jobs/{j['id']}"),'request')['references'][0]['current'])

    def test_invalid_destination_or_reference_rolls_back_addition(self):
        j=self.create()
        self.command(j,'add',title='추가 단계',before_id='missing',status=422)
        self.command(j,'add',title='추가 단계',references=[dict(origin='knowledge',id='missing',unit=0,sha256='0'*64)],status=422)
        self.assertEqual(j,self.req('GET',f"/jobs/{j['id']}"))

    def test_generic_collection_does_not_receive_education_workflow(self):
        self.assertIsNone(workflow.project(None,dict(layout={'kind':'generic'})))

    def test_locked_unrelated_document_does_not_break_reference_catalog(self):
        from app import knowledge,store,folders
        locked=MagicMock();locked.is_symlink.return_value=False;locked.is_file.return_value=True
        locked.read_bytes.side_effect=PermissionError('file in use')
        notes=MagicMock();notes.__enter__.return_value.execute.return_value.fetchall.return_value=[]
        with patch.object(knowledge,'sources',return_value=[]),patch.object(store,'list_documents',return_value=[dict(id='locked',sha256='a'*64)]),patch.object(store,'document_path',return_value=locked),patch.object(store,'all_chunks',return_value=[]),patch.object(folders,'db',return_value=notes),adhoc.db() as c:
            self.assertEqual(self.real_catalog(c),[])
        locked.read_bytes.assert_called_once()

    def test_new_job_keeps_definition_snapshot_when_default_changes(self):
        j=self.create()
        changed=workflow.default();changed['steps'][0]['title']='나중에 변경된 기본 안내'
        with patch.object(workflow,'default',return_value=changed):
            self.assertEqual(self.req('GET',f"/jobs/{j['id']}")['workflow']['steps'][0]['title'],'안내 확인')


if __name__=='__main__':unittest.main()
