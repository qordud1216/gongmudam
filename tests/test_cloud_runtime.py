"""Real Uvicorn, HTTP, SQLite, upload/download and process restart in an isolated volume."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[1]


class CloudRuntimeTests(unittest.TestCase):
    def test_no_llm_core_survives_a_real_process_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'state'
            image = os.environ.get('GONGMUDAM_TEST_IMAGE')
            volume = 'gongmudam-test-' + uuid.uuid4().hex if image else None
            volumes = [volume] if image else []
            name = 'gongmudam-test-' + uuid.uuid4().hex if image else None
            setup_command = (["docker", "run", "--rm", "--mount", f'type=volume,src={volume},dst=/var/lib/gongmudam',
                              image, 'python', 'tools/cloud_release.py', 'initialize', '--data-root', '/var/lib/gongmudam'] if image
                             else [sys.executable, 'tools/cloud_release.py', 'initialize', '--data-root', str(state)])
            setup = subprocess.run(setup_command,
                                   cwd=ROOT, capture_output=True, text=True)
            if setup.returncode and image:
                subprocess.run(['docker', 'volume', 'rm', volume], capture_output=True)
            self.assertEqual(setup.returncode, 0, setup.stderr)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
            jwk.update(kid='synthetic-runtime', use='sig', alg='RS256')
            jwks = root / 'public-test-keys.json'
            jwks.write_text(json.dumps({'keys': [jwk]}))
            jwks.chmod(0o644)  # Public test verification keys, readable by the non-root container.
            now = int(time.time())
            token = jwt.encode(dict(iss='https://synthetic-test.cloudflareaccess.com', aud='a' * 64,
                                    email='owner@example.test', sub='synthetic-owner', iat=now, exp=now + 600),
                               key, algorithm='RS256', headers={'kid': 'synthetic-runtime'})
            env = dict(os.environ, GONGMUDAM_DATA_ROOT=str(state), GONGMUDAM_DEVELOPMENT='1',
                       GONGMUDAM_ACCESS_TEAM_DOMAIN='synthetic-test.cloudflareaccess.com',
                       GONGMUDAM_ACCESS_AUD='a' * 64, GONGMUDAM_OWNER_EMAIL='owner@example.test',
                       GONGMUDAM_ACCESS_JWKS_FILE=str(jwks), PYTHONDONTWRITEBYTECODE='1')
            with socket.socket() as bound:
                bound.bind(('127.0.0.1', 0))
                port = bound.getsockname()[1]
            client = httpx.Client(base_url=f'http://127.0.0.1:{port}',
                                  headers={'Cf-Access-Jwt-Assertion': token}, timeout=20, trust_env=False)
            process = None
            log = root / 'server.log'
            def stop():
                nonlocal process
                if image:
                    subprocess.run(['docker', 'stop', '--time', '10', name], capture_output=True)
                    subprocess.run(['docker', 'rm', name], capture_output=True)
                    return
                if process is not None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    process = None
            def start():
                nonlocal process
                if image:
                    immutable = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()
                    command = ['docker', 'run', '-d', '--name', name, '--read-only',
                               '--tmpfs', '/tmp:size=128m,mode=1777', '-p', f'127.0.0.1:{port}:8892',
                               '--mount', f'type=volume,src={volume},dst=/var/lib/gongmudam',
                               '--mount', f'type=bind,src={jwks},dst=/run/test-public-keys.json,readonly']
                    keys = ['GONGMUDAM_ACCESS_TEAM_DOMAIN', 'GONGMUDAM_ACCESS_AUD', 'GONGMUDAM_OWNER_EMAIL']
                    if os.environ.get('GONGMUDAM_TEST_ALLOW_DIRTY_IMAGE') == '1':
                        keys.append('GONGMUDAM_DEVELOPMENT')
                    for key in keys:
                        command += ['-e', f'{key}={env[key]}']
                    command += ['-e', 'GONGMUDAM_IMAGE_ID=' + immutable,
                                '-e', 'GONGMUDAM_ACCESS_JWKS_FILE=/run/test-public-keys.json', image]
                    launched = subprocess.run(command, capture_output=True, text=True)
                    self.assertEqual(launched.returncode, 0, launched.stderr)
                else:
                    with log.open('ab') as stream:
                        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'integration.cloud:create_app',
                            '--factory', '--host', '127.0.0.1', '--port', str(port), '--no-access-log'],
                            cwd=ROOT, env=env, stdout=stream, stderr=stream)
                for _ in range(150):
                    if process is not None and process.poll() is not None:
                        self.fail(log.read_text())
                    try:
                        if client.get('/health/live').status_code == 200:
                            return
                    except httpx.HTTPError:
                        pass
                    time.sleep(.05)
                details = subprocess.run(['docker', 'logs', name], capture_output=True, text=True).stderr if image else log.read_text()
                self.fail('Server did not start: ' + details)
            try:
                start()
                ready = client.get('/health/ready')
                self.assertEqual(ready.status_code, 200, ready.text)
                self.assertFalse(ready.json()['llm_enabled'])
                self.assertEqual(httpx.get(client.base_url.join('/desktop/'), trust_env=False).status_code, 401)
                self.assertEqual(client.get('/desktop/').status_code, 200)
                self.assertIn('/desktop/cloud.js', client.get('/desktop/').text)
                directory = client.get('/api/agencies', params={'q': '서울특별시'}).json()
                self.assertGreater(directory['total'], 0)
                self.assertTrue(all(isinstance(item['code'], str) and len(item['code']) == 7 for item in directory['items']))
                self.assertEqual(client.get('/api/workspace/status').status_code, 200)
                bootstrap = client.get('/api/travel/bootstrap')
                self.assertEqual(bootstrap.status_code, 200)
                self.assertTrue(bootstrap.json()['organizations'])
                trip = dict(organization_id='demo-national', work_pattern='일반근무', destination='부산', purpose='합성 검증',
                            start_date='2026-10-15', end_date='2026-10-17', transport='철도', overnight=True, meals_provided=False)
                travel = client.post('/api/travel/cases', json=trip)
                self.assertEqual(travel.status_code, 201, travel.text)
                case_id = travel.json()['id']
                folder = client.post('/api/folders/uploads', data={'name': '합성 클라우드 자료', 'paths': json.dumps(['합성자료/안내.txt'])},
                    files=[('files', ('안내.txt', '합성 교육 안내 자료입니다.\n업무명: 합성 교육\n연도: 2026'.encode(), 'text/plain'))])
                self.assertEqual(folder.status_code, 201, folder.text)
                library_id = folder.json()['id']
                self.assertEqual(folder.json()['summary']['files'], 1)
                self.assertEqual(client.post('/api/workspace/model-check', json={}).status_code, 503)
                reply = client.post('/api/ask', json={'query': '국가공무원이 출장 후 운임과 숙박비 정산을 신청할 때 신청기한과 증거서류는 어떻게 되나요?',
                                                      'today': '2026-10-20', 'guidance': True, 'use_ai': False})
                self.assertEqual(reply.status_code, 200, reply.text)
                self.assertIsNone(reply.json().get('model'))
                self.assertIn('2주일 이내', reply.json()['answer'])
                self.assertTrue(reply.json()['knowledge']['evidence'])
                event = dict(title='합성 릴리즈 검토', start='2026-11-02', end='2026-11-03', all_day=True,
                             kind='event', location='', notes='', recurrence='none')
                created = client.post('/api/calendar/events', json=event)
                self.assertEqual(created.status_code, 201, created.text)
                event_id = created.json()['id']
                content = '합성 클라우드 저장·재시작 검증 자료입니다.'.encode()
                document = client.post('/api/documents', data={'title': '합성 저장 검증', 'kind': '규정', 'layer': '기관'},
                                       files={'file': ('synthetic.txt', content, 'text/plain')})
                self.assertEqual(document.status_code, 200, document.text)
                document_id = document.json()['id']
                stop()
                start()
                self.assertEqual(client.get(f'/api/calendar/events/{event_id}').json()['event']['title'], event['title'])
                self.assertEqual(client.get(f'/api/folders/libraries/{library_id}').json()['summary']['files'], 1)
                self.assertEqual(client.get(f'/api/travel/cases/{case_id}').status_code, 200)
                download = client.get(f'/api/documents/{document_id}/download')
                self.assertEqual(download.status_code, 200, download.text)
                self.assertEqual(download.content, content)
                exported = client.get('/api/calendar/export.ics', params={'start': '2026-11-01', 'end': '2026-11-05'})
                self.assertEqual(exported.status_code, 200)
                self.assertIn('합성 릴리즈 검토', exported.text)
                self.assertFalse(client.get('/api/gongmudam/status').json()['requires_origin_pc'])
                if image:
                    busy = subprocess.run(['docker', 'exec', name, 'python', 'tools/cloud_backup.py', 'backup',
                        '--data-root', '/var/lib/gongmudam', '--output', '/tmp/not-created-backup.tar.gz'], capture_output=True, text=True)
                    self.assertNotEqual(busy.returncode, 0)
                    self.assertIn('Stop the app', busy.stderr)
                    stop()
                    # Initial archived originals + this attachment exceed the 128MiB tmpfs.
                    padded = subprocess.run(['docker', 'run', '--rm', '--mount',
                        f'type=volume,src={volume},dst=/var/lib/gongmudam', image, 'python', '-c',
                        "from pathlib import Path; Path('/var/lib/gongmudam/data/synthetic-padding.bin').write_bytes(bytes(40*1024*1024))"],
                        capture_output=True, text=True)
                    self.assertEqual(padded.returncode, 0, padded.stderr)
                    backups = root / 'synthetic-backups'
                    backups.mkdir()
                    backups.chmod(0o777)  # Empty synthetic test directory, never an actual user backup store.
                    mounts = ['--mount', f'type=volume,src={volume},dst=/var/lib/gongmudam',
                              '--mount', f'type=bind,src={backups},dst=/backup']
                    saved = subprocess.run(['docker', 'run', '--rm', '--read-only', '--tmpfs', '/tmp:size=128m', *mounts,
                        image, 'python', 'tools/cloud_backup.py', 'backup', '--data-root', '/var/lib/gongmudam',
                        '--output', '/backup/synthetic.tar.gz', '--staging-root', '/backup/work'], capture_output=True, text=True)
                    self.assertEqual(saved.returncode, 0, saved.stderr)
                    backup_hash = json.loads(saved.stdout)['sha256']
                    recovered_volume = 'gongmudam-test-' + uuid.uuid4().hex
                    volumes.append(recovered_volume)
                    recovered = subprocess.run(['docker', 'run', '--rm', '--read-only', '--tmpfs', '/tmp:size=128m',
                        '--mount', f'type=volume,src={recovered_volume},dst=/var/lib/gongmudam',
                        '--mount', f'type=bind,src={backups},dst=/backup', image, 'python', 'tools/cloud_backup.py',
                        'restore', '--archive', '/backup/synthetic.tar.gz', '--sha256', backup_hash,
                        '--data-root', '/var/lib/gongmudam', '--staging-root', '/backup/work'], capture_output=True, text=True)
                    self.assertEqual(recovered.returncode, 0, recovered.stderr)
                    volume = recovered_volume
                    start()
                    self.assertEqual(client.get(f'/api/documents/{document_id}/download').content, content)
                    self.assertEqual(client.get(f'/api/calendar/events/{event_id}').json()['event']['title'], event['title'])
            finally:
                stop()
                client.close()
                if image:
                    for created_volume in volumes:
                        subprocess.run(['docker', 'volume', 'rm', created_volume], capture_output=True)


if __name__ == '__main__':
    unittest.main()
