"""첫 실행 상태 조회는 추론·자료 변경 없이 준비 상태만 반환한다."""
import unittest
from unittest.mock import patch
import httpx
import test_core
from app import config,workspace,travel_api


class WorkspaceTest(test_core.Base):
    def setUp(self): travel_api.initialize()

    def test_installed_pair_is_separate_from_inference_success(self):
        response=httpx.Response(200,request=httpx.Request('GET','http://127.0.0.1:11434/api/tags'),json={'models':[{'name':'gemma3:4b','digest':'gemma-hash'},{'name':'llama3.2:3b','digest':'llama-hash'}]})
        with patch.object(workspace.httpx,'get',return_value=response): result=workspace.status()
        self.assertTrue(result['local_server_available'])
        self.assertEqual(result['local_pair_installed'],{'gemma':True,'llama':True})
        self.assertIn('실제 모델 응답 성공을 뜻하지',result['notice'])

    def test_server_down_does_not_block_workflow_status(self):
        with patch.object(workspace.httpx,'get',side_effect=httpx.ConnectError('offline')): result=workspace.status()
        self.assertFalse(result['local_server_available']);self.assertEqual(result['installed_models'],[])
        self.assertGreater(result['resources']['procedures'],0)
        self.assertGreater(result['resources']['organizations'],0)

    def test_bad_server_data_is_not_marked_ready(self):
        with patch.object(workspace.httpx,'get',return_value=httpx.Response(500,request=httpx.Request('GET','http://127.0.0.1:11434/api/tags'),text='error')): result=workspace.status()
        self.assertFalse(result['local_server_available'])

    def test_no_keys_or_profile_identity_exposed(self):
        cfg=config.load();cfg['llm']['active']='test-secret';cfg['llm']['profiles']['test-secret']={'provider':'openai_compatible','model':'demo','api_key':'do-not-expose','base_url':'https://secret.invalid'};config.save(cfg)
        with patch.object(workspace.httpx,'get',side_effect=httpx.ConnectError('offline')): result=workspace.status()
        self.assertEqual(result['active_model']['model'],'demo')
        self.assertNotIn('do-not-expose',str(result));self.assertNotIn('secret.invalid',str(result))

    def test_status_does_not_write_cases(self):
        with travel_api.db() as c: before=c.execute('SELECT count(*) FROM travel_events').fetchone()[0]
        with patch.object(workspace.httpx,'get',side_effect=httpx.ConnectError('offline')): workspace.status()
        with travel_api.db() as c: self.assertEqual(c.execute('SELECT count(*) FROM travel_events').fetchone()[0],before)
