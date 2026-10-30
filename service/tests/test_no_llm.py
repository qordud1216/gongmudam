"""No-LLM runtime is enforced below the UI and never contacts a model server."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import config, folder_ai, llm, local_ai, workspace


class NoLLMTests(unittest.TestCase):
    def test_config_discovery_and_direct_provider_calls_cannot_enable_network_inference(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'GONGMUDAM_NO_LLM': '1'}), \
                patch.object(config, 'CONFIG_PATH', Path(tmp) / 'config.json'), \
                patch.object(llm.httpx, 'post', side_effect=AssertionError('model POST must never run')) as post, \
                patch.object(llm.httpx, 'get', side_effect=AssertionError('model discovery must never run')) as get:
            profile = {'provider': 'openai_compatible', 'base_url': 'http://127.0.0.1:11434/v1', 'model': 'synthetic'}
            config.CONFIG_PATH.write_text(json.dumps({'llm': {'active': 'synthetic', 'profiles': {'synthetic': profile}}}))
            self.assertEqual(config.active_profile()['provider'], 'offline')
            self.assertFalse(llm.get_provider(profile).available)
            with self.assertRaises(llm.LLMError):
                llm.OpenAICompatibleProvider(profile).chat([{'role': 'user', 'content': 'synthetic'}])
            with self.assertRaises(llm.LLMError):
                folder_ai.call_model(profile, [])
            changed = config.load()
            changed['llm'] = {'active': 'synthetic', 'profiles': {'synthetic': profile}}
            with self.assertRaises(ValueError):
                config.save(changed)
            app = FastAPI()
            app.include_router(workspace.router)
            with TestClient(app) as client:
                status = client.get('/api/workspace/model-status')
                self.assertEqual(status.status_code, 200)
                self.assertTrue(status.json()['offline'])
            self.assertTrue(local_ai.options()['disabled'])
            post.assert_not_called()
            get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
