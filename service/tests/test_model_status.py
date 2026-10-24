"""Observable selected-model states; no real model or user data is used here."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
from app import config, llm, model_status as ms
from app.main import app, api_llm


class ModelStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.profile = dict(provider='openai_compatible', base_url='http://127.0.0.1:19848/prefix/v1', model='demo-a', api_key='PRIVATE-KEY', timeout=180)
        self.cfg = dict(llm=dict(active='a', profiles=dict(a=self.profile, b=self.profile | dict(model='demo-b'), offline=dict(provider='offline'))))
        self.patches = [patch.object(config, 'CONFIG_PATH', Path(self.tmp.name)/'config.json'), patch.object(ms, '_inflight', None), patch.object(ms, '_last_response', None), patch.object(ms, '_check_lock', threading.Lock())]
        for item in self.patches:
            item.start()
        config.save(self.cfg)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def models(self, ids=('demo-a', 'demo-b'), status=200, payload=None):
        return httpx.Response(status, request=httpx.Request('GET', self.profile['base_url']+'/models'), json={'data': [{'id': item} for item in ids]} if payload is None else payload)

    def completion(self, model='demo-a', content='{"ok":true}', status=200):
        payload = {'choices': [{'message': {'content': content}}]}
        if model is not None:
            payload['model'] = model
        return httpx.Response(status, request=httpx.Request('POST', self.profile['base_url']+'/chat/completions'), json=payload)

    def snapshot(self):
        with patch.object(ms.httpx, 'get', return_value=self.models()):
            return ms.snapshot()

    def test_selected_url_model_and_auth_are_used_without_inference(self):
        with patch.object(ms.httpx, 'get', return_value=self.models()) as get, patch.object(llm.httpx, 'post') as post:
            value = ms.snapshot()
        self.assertEqual(get.call_args.args[0], self.profile['base_url']+'/models')
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer PRIVATE-KEY')
        self.assertFalse(get.call_args.kwargs['follow_redirects'])
        post.assert_not_called()
        self.assertEqual(value['connection']['state'], 'ready')
        self.assertEqual(value['response']['state'], 'unverified')
        self.assertNotIn('PRIVATE-KEY', json.dumps(value))
        self.assertNotIn('19848', json.dumps(value))

    def test_offline_and_external_never_probe(self):
        for name, values, expected in [('offline', dict(provider='offline'), 'offline'), ('a', dict(provider='openai_compatible', base_url='https://private-server.invalid/v1', model='demo-a'), 'external')]:
            with self.subTest(expected):
                cfg=copy.deepcopy(self.cfg);cfg['llm']['active']=name;cfg['llm']['profiles'][name]=values;config.save(cfg)
                with patch.object(ms.httpx, 'get') as get, patch.object(llm.httpx, 'post') as post:
                    value=ms.snapshot()
                    self.assertEqual(value['connection']['state'], expected)
                    with self.assertRaises(HTTPException) as caught:
                        ms.check(value['selection_id'])
                    self.assertEqual(caught.exception.status_code, 422)
                get.assert_not_called();post.assert_not_called()
                self.assertNotIn('private-server.invalid', json.dumps(value))

    def test_bad_local_targets_are_not_probed(self):
        for endpoint in ['http://user:secret@127.0.0.1:12/v1', 'http://127.0.0.1:12/v1?key=secret', 'http://127.0.0.1:99999/v1', 'not-a-url', 'http://127.0.0.1:0/v1']:
            cfg=copy.deepcopy(self.cfg);cfg['llm']['profiles']['a']['base_url']=endpoint;config.save(cfg)
            with patch.object(ms.httpx, 'get') as get:
                value=ms.snapshot()
            self.assertEqual(value['connection']['state'], 'invalid')
            get.assert_not_called()

    def test_missing_model_and_exact_model_matching(self):
        with patch.object(ms.httpx, 'get', return_value=self.models(ids=['demo-b', 'demo-a-other'])):
            self.assertEqual(ms.snapshot()['connection']['state'], 'model_missing')
        with patch.object(ms.httpx, 'get', return_value=self.models(ids=['demo-a:latest'])):
            self.assertEqual(ms.snapshot()['connection']['state'], 'ready')

    def test_http_and_invalid_listing_states(self):
        for response, state in [(self.models(status=401),'unauthorized'),(self.models(status=403),'unauthorized'),(self.models(status=503),'server_error'),(self.models(status=404),'unsupported'),(self.models(status=302),'unsupported'),(self.models(payload={'other': []}),'invalid_response'),(self.models(payload={'data': [None]}),'invalid_response')]:
            with self.subTest(state), patch.object(ms.httpx, 'get', return_value=response):
                self.assertEqual(ms.snapshot()['connection']['state'], state)
        with patch.object(ms.httpx, 'get', side_effect=httpx.ConnectError('PRIVATE-BODY')):
            value=ms.snapshot()
        self.assertEqual(value['connection']['state'], 'unreachable')
        self.assertNotIn('PRIVATE-BODY', json.dumps(value))

    def test_only_matching_nonempty_completion_is_verified(self):
        token=self.snapshot()['selection_id']
        with patch.object(llm.httpx, 'post', return_value=self.completion()) as post:
            value=ms.check(token)
        self.assertEqual(value['response']['state'], 'verified')
        self.assertEqual(value['response']['characters'], 11)
        self.assertEqual(post.call_args.args[0], self.profile['base_url']+'/chat/completions')
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer PRIVATE-KEY')
        self.assertEqual(post.call_args.kwargs['timeout'], 60)
        self.assertNotIn('{"ok":true}', json.dumps(value))
        self.assertNotIn('PRIVATE-KEY', json.dumps(value))
        self.assertEqual(self.snapshot()['response']['state'], 'verified')

    def test_wrong_missing_empty_and_failed_responses_never_verify(self):
        token=self.snapshot()['selection_id']
        for response,state in [(self.completion(model='demo-b'),'model_mismatch'),(self.completion(model=None),'model_unverified'),(self.completion(content=''),'empty'),(self.completion(status=404),'failed')]:
            with self.subTest(state), patch.object(llm.httpx, 'post', return_value=response):
                self.assertEqual(ms.check(token)['response']['state'], state)
        with patch.object(llm.httpx, 'post', side_effect=httpx.ConnectError('PRIVATE-FAILURE')):
            value=ms.check(token)
        self.assertEqual(value['response']['state'], 'failed')
        self.assertNotIn('PRIVATE-FAILURE', json.dumps(value))

    def test_discovery_not_supported_does_not_prevent_explicit_check(self):
        with patch.object(ms.httpx, 'get', return_value=self.models(status=404)):
            token=ms.snapshot()['selection_id']
        with patch.object(llm.httpx, 'post', return_value=self.completion()):
            self.assertEqual(ms.check(token)['response']['state'], 'verified')

    def test_token_changes_for_active_model_endpoint_and_effective_environment_key(self):
        original=self.snapshot()['selection_id']
        for field,value in [('model','other'),('base_url','http://localhost:19999/v1'),('api_key','replacement')]:
            cfg=copy.deepcopy(self.cfg);cfg['llm']['profiles']['a'][field]=value;config.save(cfg)
            self.assertNotEqual(self.snapshot()['selection_id'],original)
        cfg=copy.deepcopy(self.cfg);cfg['llm']['profiles']['a']['api_key_env']='SEOMU_UNIT_TEST_TOKEN';config.save(cfg)
        with patch.dict('os.environ', {'SEOMU_UNIT_TEST_TOKEN':'env-first'}):
            first=self.snapshot()['selection_id']
        with patch.dict('os.environ', {'SEOMU_UNIT_TEST_TOKEN':'env-second'}),patch.object(ms.httpx,'get',return_value=self.models()) as get:
            second=ms.snapshot()['selection_id']
        self.assertNotEqual(first,second)
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'],'Bearer env-second')

    def test_switch_away_and_back_invalidates_prior_evidence(self):
        token=self.snapshot()['selection_id']
        with patch.object(llm.httpx,'post',return_value=self.completion()):ms.check(token)
        api_llm(dict(active='b'));api_llm(dict(active='a'))
        now=self.snapshot()
        self.assertNotEqual(now['selection_id'],token)
        self.assertEqual(now['response']['state'],'unverified')
        with self.assertRaises(HTTPException) as caught:ms.check(token)
        self.assertEqual(caught.exception.status_code,409)

    def test_saving_unchanged_values_does_not_invalidate_test(self):
        token=self.snapshot()['selection_id']
        api_llm(dict(profile='a',values=dict(model='demo-a'),active='a'))
        self.assertEqual(self.snapshot()['selection_id'],token)
        api_llm(dict(profile='b',values=dict(model='unselected-edit')))
        self.assertEqual(self.snapshot()['selection_id'],token)

    def test_late_discovery_after_switch_is_rejected(self):
        def changed(*args,**kwargs):
            api_llm(dict(active='b'));return self.models()
        with patch.object(ms.httpx,'get',side_effect=changed),self.assertRaises(HTTPException) as caught:
            ms.snapshot()
        self.assertEqual(caught.exception.detail['code'],'selection_changed')

    def test_late_completion_after_switch_is_not_published(self):
        token=self.snapshot()['selection_id']
        def changed(*args,**kwargs):
            api_llm(dict(active='b'));return self.completion()
        with patch.object(llm.httpx,'post',side_effect=changed),self.assertRaises(HTTPException) as caught:
            ms.check(token)
        self.assertEqual(caught.exception.detail['code'],'selection_changed')
        self.assertEqual(self.snapshot()['response']['state'],'unverified')
        api_llm(dict(active='a'))
        self.assertEqual(self.snapshot()['response']['state'],'unverified')

    def test_parallel_checks_are_rejected_and_state_is_recovered(self):
        token=self.snapshot()['selection_id'];entered=threading.Event();release=threading.Event();results=[]
        def delayed(*args,**kwargs):
            entered.set();release.wait(3);return self.completion()
        with patch.object(llm.httpx,'post',side_effect=delayed) as post:
            thread=threading.Thread(target=lambda:results.append(ms.check(token)));thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.snapshot()['check_in_progress'])
                self.assertEqual(self.snapshot()['response']['state'],'checking')
                with self.assertRaises(HTTPException) as caught:ms.check(token)
                self.assertEqual(caught.exception.detail['code'],'check_busy')
            finally:release.set();thread.join(3)
        self.assertEqual(post.call_count,1)
        self.assertEqual(results[0]['response']['state'],'verified')
        self.assertFalse(self.snapshot()['check_in_progress'])

    def test_old_test_is_expired_and_current_failure_is_still_visible(self):
        token=self.snapshot()['selection_id']
        with patch.object(ms.time,'monotonic',return_value=1000),patch.object(llm.httpx,'post',return_value=self.completion()):ms.check(token)
        with patch.object(ms.time,'monotonic',return_value=1001),patch.object(ms.httpx,'get',side_effect=httpx.ConnectError('down')):
            value=ms.snapshot()
        self.assertEqual(value['connection']['state'],'unreachable')
        self.assertEqual(value['response']['state'],'verified')
        with patch.object(ms.time,'monotonic',return_value=1000+ms.EVIDENCE_TTL+1):
            self.assertEqual(self.snapshot()['response']['state'],'expired')

    def test_concurrent_settings_save_cannot_restore_old_selection_revision(self):
        entered=threading.Event();release=threading.Event();done=threading.Event();failures=[]
        save=config.save
        def delayed(cfg):
            if threading.current_thread().name=='select-b':
                entered.set();release.wait(3)
            save(cfg)
        def run(body,finished=None):
            try:api_llm(body)
            except Exception as error:failures.append(error)
            finally:
                if finished:finished.set()
        with patch.object(config,'save',side_effect=delayed):
            first=threading.Thread(name='select-b',target=run,args=(dict(active='b'),));first.start()
            second=None
            try:
                self.assertTrue(entered.wait(2))
                second=threading.Thread(target=run,args=(dict(profile='a',values=dict(model='demo-a')),done));second.start()
                self.assertFalse(done.wait(.05))
            finally:
                release.set();first.join(3)
                if second:second.join(3)
        self.assertFalse(failures)
        self.assertEqual(config.load()['llm']['active'],'b')
        self.assertEqual(config.load()['llm']['_selection_revision'],1)

    def test_fixed_synthetic_request_and_bounded_output_even_with_extra_body(self):
        cfg=copy.deepcopy(self.cfg);cfg['llm']['profiles']['a']['extra_body']=dict(messages=[dict(role='user',content='PRIVATE-WORK-DATA')],stream=True,max_tokens=100000,response_format=dict(type='json_object'))
        config.save(cfg);token=self.snapshot()['selection_id']
        with patch.object(llm.httpx,'post',return_value=self.completion()) as post:ms.check(token)
        body=post.call_args.kwargs['json']
        self.assertNotIn('PRIVATE-WORK-DATA',json.dumps(body))
        self.assertNotIn('stream',body)
        self.assertEqual(body['max_tokens'],64)
        self.assertEqual(body['response_format'],dict(type='json_object'))

    def test_routes_validate_selection_and_preserve_plain_status_contract(self):
        client=TestClient(app)
        with patch.object(ms.httpx,'get',return_value=self.models()):
            response=client.get('/api/workspace/model-status')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['profile'],'a')
        self.assertEqual(client.post('/api/workspace/model-check',json={}).status_code,422)
        self.assertEqual(client.post('/api/workspace/model-check',json={'selection_id':'x'*64,'profile':'b'}).status_code,422)
        self.assertEqual(client.post('/api/workspace/model-check',json={'selection_id':'x'*64}).status_code,409)


if __name__=='__main__':
    unittest.main()
