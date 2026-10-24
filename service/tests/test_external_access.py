import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools import external_access as ext

class ExternalAccessTest(unittest.TestCase):
 def test_require_exact_nonempty_emails_and_no_wildcards(self):
  for values in ([],[''],['*@example.com'],['*'],['a@example.com --hello-world'],['--bad@example.com'],['person@localhost'],['a@example.com\nX:y']):
   with self.subTest(values=values),self.assertRaises(ValueError):ext.emails(values)
 def test_normalize_and_deduplicate_emails(self):self.assertEqual(ext.emails([' User@Example.com ','user@example.com','second@example.com']),['user@example.com','second@example.com'])
 def test_command_always_requires_email_auth_and_exposes_only_app_port(self):
  args=ext.command('cloudflared.exe',ext.origin(8766),['user@example.com','second@example.com'],Path('test.log'))
  self.assertEqual(args.count('--allowed-mail'),2);self.assertEqual(args[args.index('--url')+1],'http://127.0.0.1:8766');self.assertIn('--management-diagnostics=false',args);self.assertNotIn('0.0.0.0',str(args))
 def test_no_unauthenticated_command_fallback(self):
  with self.assertRaises(ValueError):ext.command('cloudflared.exe','http://127.0.0.1:8766',[],Path('test.log'))
 def test_remote_and_wildcard_origins_rejected(self):
  for url in ('http://localhost:8766','http://0.0.0.0:8766','https://example.com','http://127.0.0.1:8766/path'):
   with self.subTest(url=url),self.assertRaises(ValueError):ext.command('cf',url,['user@example.com'],Path('test.log'))
 def test_invalid_ports_rejected(self):
  for port in (-1,0,80,65536,True,'8766'):
   with self.subTest(port=port),self.assertRaises(ValueError):ext.origin(port)
 def test_auth_unsupported_client_rejected_before_publication(self):
  with patch.object(ext.shutil,'which',return_value='fake.exe'),patch.object(ext.subprocess,'check_output',return_value='old client no flag'),self.assertRaises(ValueError):ext.cloudflared()
 def test_app_identity_requires_expected_openapi_title_and_routes(self):
  import io,json
  for obj,wanted in [({'info':{'title':'another app'},'paths':{}},False),({'info':{'title':'서무비서'},'paths':{'/api/folders/change-inbox':{}}},True)]:
   with patch.object(ext,'urlopen',return_value=io.BytesIO(json.dumps(obj).encode())):self.assertEqual(ext.app_ready('http://127.0.0.1:8766'),wanted)
 def test_log_url_is_only_a_valid_trycloudflare_hostname(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(ext,'PRIVATE',Path(temp)):
   log=Path(temp)/'a.log';log.write_text('https://evil.example https://demo-good.trycloudflare.com https://evil.trycloudflare.com.evil.org',encoding='utf-8');self.assertEqual(ext.public_url({'log':str(log)}),'https://demo-good.trycloudflare.com')
 def test_public_status_redacts_email_addresses(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(ext,'PRIVATE',Path(temp)),patch.object(ext,'tracked',return_value=False):
   ext.write(Path(temp)/'settings.json',dict(allowed_emails=['private@example.com']));result=ext.status();self.assertEqual(result['allowed_email_count'],1);self.assertNotIn('private@example.com',str(result));self.assertIsNone(result['url'])
 def test_stop_never_kills_unverified_process(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(ext,'PRIVATE',Path(temp)),patch.object(ext,'tracked',return_value=False),patch.object(ext.subprocess,'run') as run:
   ext.write(Path(temp)/'state.json',{'pid':1234});self.assertFalse(ext.stop()['stopped']);run.assert_not_called()
 def test_logs_outside_private_directory_not_read(self):
  with tempfile.TemporaryDirectory() as temp:
   log=Path(temp)/'a.log';log.write_text('https://private.trycloudflare.com');self.assertIsNone(ext.public_url({'log':str(log)}))
