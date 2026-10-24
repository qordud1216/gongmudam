"""모의 응답으로 검증기의 오판을 막는 회귀시험. 제출용 실제 구동 증거와 별개."""
import json
import unittest
from unittest.mock import patch
import httpx
import test_core
from app import config,local_ai,llm
from fastapi import HTTPException


class LocalAiTest(test_core.Base):
    def setUp(self):
        cfg=config.load()
        cfg['llm']['profiles']['unit_local']={'provider':'openai_compatible','base_url':'http://127.0.0.1:11434/v1','model':'unit-test-model','api_key':'unit-test-secret','timeout':1}
        config.save(cfg)

    def response(self,card='card-travel',text=None):
        return httpx.Response(200,json={'model':'unit-test-model','choices':[{'message':{'content':text if text is not None else json.dumps({'card_id':card,'answer':'증빙서류를 첨부하세요.','cited':[]})}}],'usage':{'prompt_tokens':10,'completion_tokens':10}})

    def test_real_call_required_for_pass(self):
        with patch.object(llm.httpx,'post',return_value=self.response()):
            result=local_ai.run(local_ai.Run(profile='unit_local',scenario='travel'))
        self.assertTrue(result['passed'])
        self.assertEqual(result['response_model'],'unit-test-model')
        self.assertEqual(len(result['model_calls']),1)
        self.assertNotIn('unit-test-secret',json.dumps(result))

    def test_wrong_model_card_is_not_hidden_by_app_selection(self):
        with patch.object(llm.httpx,'post',return_value=self.response('not-a-card')):
            result=local_ai.run(local_ai.Run(profile='unit_local',scenario='travel'))
        self.assertFalse(result['passed'])
        self.assertFalse(result['checks']['model_selected_expected_card'])

    def test_fallback_does_not_count_as_model_success(self):
        with patch.object(llm.httpx,'post',side_effect=httpx.ConnectError('unit-only')):
            result=local_ai.run(local_ai.Run(profile='unit_local',scenario='travel'))
        self.assertEqual(result['result']['mode'],'fallback')
        self.assertFalse(result['passed']);self.assertEqual(result['model_calls'],[])

    def test_bad_json_response_cannot_pass(self):
        with patch.object(llm.httpx,'post',return_value=self.response(text='not JSON')):
            result=local_ai.run(local_ai.Run(profile='unit_local',scenario='travel'))
        self.assertFalse(result['passed'])

    def test_cloud_and_unknown_profiles_rejected(self):
        for name in ['openai','offline','missing']:
            with self.assertRaises(HTTPException): local_ai.local_profile(name)

    def test_profile_override_does_not_change_global_selection(self):
        before=config.load()
        with patch.object(llm.httpx,'post',return_value=self.response()): local_ai.run(local_ai.Run(profile='unit_local',scenario='travel'))
        self.assertEqual(config.load(),before)

    def test_capture_is_scoped_to_request(self):
        provider=llm.OpenAICompatibleProvider({'base_url':'http://localhost:11434/v1','model':'unit-test-model'})
        with patch.object(llm.httpx,'post',return_value=self.response()):
            with llm.capture_calls() as a:
                provider.chat([])
                with llm.capture_calls() as b: provider.chat([])
            provider.chat([])
        self.assertEqual(len(a),1);self.assertEqual(len(b),1)

    def test_failure_check_reports_fallback_separately(self):
        with patch.object(llm.httpx,'post',side_effect=httpx.ConnectError('unit-only')): result=local_ai.failure_check()
        self.assertTrue(result['passed']);self.assertEqual(result['result']['mode'],'fallback')
