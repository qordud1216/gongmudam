import copy,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from app import public_demo
from tools import public_tunnel

class PublicDemoTest(unittest.TestCase):
 def config(self):return {'server':{'port':8767},'llm':{'active':'local_gemma','profiles':{key:dict(provider='openai_compatible',base_url='http://127.0.0.1:11434/v1',model=model,api_key='') for key,model in public_demo.MODELS.items()}}}
 def test_only_fixed_models_can_be_selected(self):
  initial=self.config();value=copy.deepcopy(initial);value['llm']['active']='local_llama';public_demo.validate_config(value,initial);self.assertEqual(initial['llm']['active'],'local_gemma')
 def test_url_key_provider_and_profile_injection_rejected(self):
  for field,value in [('base_url','http://169.254.169.254'),('api_key','injected'),('api_key_env','SECRET'),('provider','other'),('model','unregistered-model')]:
   new=self.config();new['llm']['profiles']['local_gemma'][field]=value
   with self.subTest(field=field),self.assertRaises(ValueError):public_demo.validate_config(new,self.config())
 def test_unregistered_active_model_rejected(self):
  value=self.config();value['llm']['active']='external'
  with self.assertRaises(ValueError):public_demo.validate_config(value,self.config())
 def test_server_config_change_rejected(self):
  value=self.config();value['server']['port']=8766
  with self.assertRaises(ValueError):public_demo.validate_config(value,self.config())
 def test_private_folder_rejected_before_any_filesystem_scan(self):
  with tempfile.TemporaryDirectory() as temp:
   allowed=Path(temp)/'allowed';allowed.mkdir();outside=Path(temp)/'private';outside.mkdir()
   with patch.object(public_demo,'restricted_roots',wraps=public_demo.restricted_roots):
    from unittest.mock import Mock
    scan=Mock()
    with self.assertRaises(HTTPException) as error:public_demo.restricted_roots([str(outside)],allowed,scan)
    self.assertEqual(error.exception.status_code,403);scan.assert_not_called()
 def test_only_synthetic_subdirectories_allowed(self):
  with tempfile.TemporaryDirectory() as temp:
   allowed=Path(temp);child=allowed/'reply';child.mkdir();self.assertEqual(public_demo.restricted_roots([str(child)],allowed,lambda x:[child.resolve()]),[child.resolve()])
 def test_resolved_junction_escape_rejected(self):
  with tempfile.TemporaryDirectory() as temp:
   allowed=Path(temp)/'allowed';allowed.mkdir();child=allowed/'link';outside=Path(temp)/'outside';outside.mkdir()
   with self.assertRaises(HTTPException):public_demo.restricted_roots([str(child)],allowed,lambda x:[outside.resolve()])
 def test_traversal_and_executable_files_rejected(self):
  for value in ('../private.txt','..\\private.txt','C:\\file.txt','script.py','script.txt.exe','.hidden.txt','NUL.txt','demo.ps1','a.txt\x00','bad/name.txt'):
   with self.subTest(value=value),self.assertRaises(ValueError):public_demo.safe_name(value)
 def test_synthetic_text_name_always_prefixed(self):self.assertEqual(public_demo.safe_name('간담회_회신.txt'),'공개_간담회_회신.txt')
 def test_private_app_cannot_start_public_factory(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(public_demo,'ROOT',Path(temp)):
   with self.assertRaises(RuntimeError):public_demo.create_app()
 def test_tunnel_requires_explicit_public_demo_origin(self):
  samples=[({},False),({'mode':'public-synthetic-demo','private_data_isolated':True,'pc_root_access':False},True),({'mode':'private','private_data_isolated':True,'pc_root_access':False},False),({'mode':'public-synthetic-demo','private_data_isolated':False,'pc_root_access':False},False),({'mode':'public-synthetic-demo','private_data_isolated':True,'pc_root_access':True},False)]
  for body,expected in samples:
   with self.subTest(body=body),patch.object(public_tunnel,'urlopen',return_value=io.BytesIO(json.dumps(body).encode())):self.assertEqual(public_tunnel.check_origin(),expected)
 def test_anonymous_tunnel_has_no_private_port_option(self):self.assertEqual(public_tunnel.ORIGIN,'http://127.0.0.1:8767')
