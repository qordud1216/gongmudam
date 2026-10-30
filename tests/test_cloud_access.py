"""The hosted app protects HTML, API, originals and downloads with one owner identity."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient


class CloudAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update(kid='synthetic-test', alg='RS256', use='sig')
        path = Path(self.temp.name) / 'public-test-jwks.json'
        path.write_text(json.dumps({'keys': [jwk]}))
        self.env = patch.dict(os.environ, {
            'GONGMUDAM_ACCESS_TEAM_DOMAIN': 'synthetic-test.cloudflareaccess.com',
            'GONGMUDAM_ACCESS_AUD': 'a' * 64,
            'GONGMUDAM_OWNER_EMAIL': 'owner@example.test',
            'GONGMUDAM_ACCESS_JWKS_FILE': str(path)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def token(self, **changes):
        now = int(time.time())
        claims = dict(iss='https://synthetic-test.cloudflareaccess.com', aud='a' * 64,
                      email='owner@example.test', sub='synthetic-owner', iat=now, exp=now + 300)
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm='RS256', headers={'kid': 'synthetic-test'})

    def client(self):
        from integration.cloud_access import OperatorAccess
        app = FastAPI()
        @app.get('/{path:path}')
        def all_paths(path: str):
            return {'private': True}
        app.add_middleware(OperatorAccess, release_id='synthetic-release')
        return TestClient(app)

    def test_every_surface_rejects_missing_forged_expired_and_wrong_owner_identity(self):
        client = self.client()
        for path in ('/desktop/', '/api/home', '/api/knowledge/sources/example/original', '/api/documents/example/download'):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 401)
                self.assertEqual(client.get(path, headers={'Cf-Access-Jwt-Assertion': 'forged'}).status_code, 401)
                self.assertEqual(client.get(path, headers={'Cf-Access-Jwt-Assertion': self.token(exp=int(time.time()) - 60)}).status_code, 401)
                self.assertEqual(client.get(path, headers={'Cf-Access-Jwt-Assertion': self.token(email='other@example.test')}).status_code, 403)
                ok = client.get(path, headers={'Cf-Access-Jwt-Assertion': self.token()})
                self.assertEqual(ok.status_code, 200)
                self.assertEqual(ok.headers['X-Gongmudam-Release'], 'synthetic-release')
                self.assertEqual(ok.headers['Cache-Control'], 'no-store')
        client.close()

    def test_disabled_operations_and_cross_origin_errors_keep_the_release_identity(self):
        client = self.client()
        headers = {'Cf-Access-Jwt-Assertion': self.token()}
        for path, expected in (('/api/workspace/model-check', 503), ('/api/regulations/check', 409),
                               ('/api/folders/choose-local', 403)):
            result = client.post(path, headers=headers, json={})
            self.assertEqual(result.status_code, expected)
            self.assertEqual(result.headers['X-Gongmudam-Release'], 'synthetic-release')
        denied = client.post('/api/save', headers=headers | {'Origin': 'https://other.example'}, json={})
        self.assertEqual(denied.status_code, 403)
        client.close()


if __name__ == '__main__':
    unittest.main()
