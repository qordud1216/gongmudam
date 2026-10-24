"""실제 실행 중인 앱·Ollama로 검증한다. 모의 응답을 성공 증거로 만들지 않는다."""
import argparse
import hashlib
import json
import platform
import sys
import urllib.request
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:8766')
    parser.add_argument('--output',default=str(ROOT/'docs'/'local-ai-evidence'))
    args=parser.parse_args();folder=Path(args.output);folder.mkdir(parents=True,exist_ok=True)
    def request(path,body=None):
        req=urllib.request.Request(args.base_url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        return json.load(urllib.request.urlopen(req,timeout=240))
    def save(path,data): path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    options=request('/api/local-ai/options')
    result={'schema':'local-ai-proof/1','created_at':datetime.now(timezone.utc).isoformat(),'environment':{'os':platform.platform(),'python':platform.python_version(),'ollama_version':options['ollama_version'],'installed_models':options['installed_models']},
            'scope':'합성 규정·절차 카드 기반 서무 안내. 두 로컬 모델의 실제 선택과 앱의 절차·서식·근거 표시 검증. 여비 계산 엔진은 LLM과 별개.',
            'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['app/assistant.py','app/llm.py','app/local_ai.py']},'runs':[]}
    for profile in ['local_gemma','local_llama']:
        for scenario in ['travel','leave','purchase']:
            print('RUN',profile,scenario,flush=True)
            try: evidence=request('/api/local-ai/run',{'profile':profile,'scenario':scenario})
            except Exception as exc:
                evidence={'profile':profile,'scenario_id':scenario,'passed':False,'transport_error':type(exc).__name__}
            result['runs'].append(evidence);save(folder/f'{profile}_{scenario}.json',evidence)
            print('RESULT',evidence.get('response_model'),evidence.get('passed'),evidence.get('elapsed_seconds'),flush=True)
    result['failure_check']=request('/api/local-ai/failure-check',{})
    comparisons=[]
    for scenario in ['travel','leave','purchase']:
        rows=[r for r in result['runs'] if r.get('scenario_id')==scenario]
        signatures=[json.dumps(r.get('result',{}).get('plan'),sort_keys=True,ensure_ascii=False) for r in rows]
        comparisons.append({'scenario':scenario,'same_procedure_forms_basis_deadlines':len(rows)==2 and signatures[0]==signatures[1]})
    result['comparisons']=comparisons
    result['passed']=all(r.get('passed') for r in result['runs']) and result['failure_check']['passed'] and all(c['same_procedure_forms_basis_deadlines'] for c in comparisons)
    save(folder/'local-ai-evidence.json',result)
    save(ROOT/'static'/'local-ai-evidence.json',result)
    save(folder/'sha256.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*.json')) if p.name!='sha256.json'})
    print('FINAL',result['passed'],folder,flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__': sys.exit(main())
