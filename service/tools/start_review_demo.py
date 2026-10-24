"""Start the existing apps for this review only; no boot tasks or hosting changes."""
from pathlib import Path
import re
import subprocess,json,shutil,time,urllib.request,argparse
ROOT=Path(__file__).resolve().parents[1]
def merge_public_html(main_html,public_html):
 notice=re.search(r'<div class="public-notice">.*?</div>',public_html,re.DOTALL)
 css=re.search(r'<link\b(?=[^>]*\bhref=["\'][^"\']*public-demo\.css(?:\?[^"\']*)?["\'])[^>]*>',public_html,re.IGNORECASE)
 if not notice or not css:raise ValueError('Public HTML is missing its notice or public-demo.css link')
 merged=re.sub(r'<div class="public-notice">.*?</div>','',main_html,flags=re.DOTALL)
 merged=re.sub(r'<link\b(?=[^>]*\bhref=["\'][^"\']*public-demo\.css(?:\?[^"\']*)?["\'])[^>]*>','',merged,flags=re.IGNORECASE)
 head=re.search(r'</head\s*>',merged,re.IGNORECASE)
 body=re.search(r'<body\b[^>]*>',merged,re.IGNORECASE)
 if not head or not body:raise ValueError('Main HTML is missing head or body boundary')
 merged=merged[:head.start()]+css.group(0)+'\n'+merged[head.start():]
 body=re.search(r'<body\b[^>]*>',merged,re.IGNORECASE)
 if not body:raise ValueError('Main HTML body boundary was lost')
 return merged[:body.end()]+'\n'+notice.group(0)+merged[body.end():]
def ready(port):
 try:
  with urllib.request.urlopen(f'http://127.0.0.1:{port}/openapi.json',timeout=2) as r:return json.load(r).get('info',{}).get('title')=='서무비서'
 except Exception:return False
def start(refresh=False,local_only=False):
 dest=ROOT.parent/'work/public-demo-v28b'
 if not (dest/'public-demo.json').is_file():raise RuntimeError('Missing separate public demo')
 for name in ['knowledge.py','knowledge_relevance.py','knowledge_intent.py','knowledge_supplement.py','official_sources.py','main.py','answer_tree.py','adhoc.py','adhoc_workflow.py','education_intent.py','workflow_chat.py','travel_calculator.py','travel_rates.py','travel_models.py','travel_training.py','travel_api.py','travel_validity.py','travel_package.py','travel_journey.py','regulation_registry.py','regulation_sources.py','regulation_monitor.py']:shutil.copy2(ROOT/'app'/name,dest/'app'/name)
 for name in ['knowledge-chat.js','folder-knowledge.js','app.js','start.js','workspace-flow.js','answer-tree.js','answer-tree.css','adhoc.js','adhoc.css','adhoc-workflow.js','adhoc-workflow.css','workflow-chat.js','workflow-chat.css','travel-calculation.js','travel.js','regulation-monitor.js','regulation-monitor.css']:shutil.copy2(ROOT/'static'/name,dest/'static'/name)
 shutil.copy2(ROOT/'app/rulepacks/domestic_tables_2026_10.json',dest/'app/rulepacks/domestic_tables_2026_10.json')
 shutil.copy2(ROOT/'app/rulepacks/domestic_reviewed_2026_10.json',dest/'app/rulepacks/domestic_reviewed_2026_10.json')
 shutil.copy2(ROOT/'reference_data/easy_summaries_v35.json',dest/'reference_data/easy_summaries_v35.json')
 for name in ['index.html','start.html','adhoc.html','travel.html','change-inbox.html']:
  main_html=(ROOT/'static'/name).read_text(encoding='utf-8')
  public_html=(dest/'static'/name).read_text(encoding='utf-8')
  (dest/'static'/name).write_text(merge_public_html(main_html,public_html),encoding='utf-8')
 shutil.copytree(ROOT/'reference_data/official-20261020',dest/'reference_data/official-20261020',dirs_exist_ok=True)
 shutil.copytree(ROOT/'reference_data/travel-recheck-20261020',dest/'reference_data/travel-recheck-20261020',dirs_exist_ok=True)
 ports=(8766,) if local_only else (8766,8767)
 if refresh:
  script="Get-NetTCPConnection -State Listen -LocalPort "+','.join(map(str,ports))+" -ErrorAction SilentlyContinue | ForEach-Object { $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$_.OwningProcess); if (($p.CommandLine -like '*uvicorn app.main:app*--port 8766*') -or ($p.CommandLine -like '*uvicorn app.public_demo:create_app*--port 8767*')) { Stop-Process -Id $p.ProcessId } }"
  subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],check=True,timeout=20)
  time.sleep(1)
 for port,cwd,target in [(8766,ROOT,'app.main:app'),(8767,dest,'app.public_demo:create_app')]:
  if port not in ports:continue
  if ready(port):print('Already running',port);continue
  cmd=[str(ROOT/'.venv/Scripts/python.exe'),'-m','uvicorn',target,'--host','127.0.0.1','--port',str(port)]
  if port==8767:cmd+=['--factory']
  with (ROOT.parent/'work'/f'review-v32-{port}.log').open('ab') as log:
   p=subprocess.Popen(cmd,cwd=cwd,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
  print('Started',port,p.pid)
 for _ in range(20):
  if all(ready(p) for p in ports):print('Ready:',','.join(map(str,ports)));return
  time.sleep(.5)
 raise RuntimeError('App startup failed: inspect review logs')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--refresh',action='store_true');p.add_argument('--local-only',action='store_true');args=p.parse_args();start(args.refresh,args.local_only)
