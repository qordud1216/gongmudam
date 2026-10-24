"""별도 설치한 서버의 초기 상태·실제 모델·정산 묶음을 검증한다."""
import argparse
import hashlib
import io
import json
import platform
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime,timezone
from importlib.metadata import version
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--candidate',required=True);parser.add_argument('--output',required=True);parser.add_argument('--url',default='http://127.0.0.1:8771')
    args=parser.parse_args();root=Path(args.candidate).resolve();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    def request(path,body=None):
        req=urllib.request.Request(args.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        return json.load(urllib.request.urlopen(req,timeout=240))
    def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    assert Path(sys.prefix).resolve()==root/'.venv','새 후보의 Python으로 실행해야 합니다.'
    manifest=json.loads((root/'submission-manifest.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in manifest['files'].items())
    settings=request('/api/settings');status=request('/api/workspace/status')
    assert settings['llm']['active']=='offline','새 설정 기본값이어야 합니다.'
    assert status['resources']['travel_cases']==0,'기존 출장 DB를 사용하면 안 됩니다.'
    expected={}
    for line in (root/'requirements-travel.lock.txt').read_text().splitlines():
        name,value=line.split('==');assert version(name)==value;expected[name]=value
    checked=subprocess.run([sys.executable,'-m','pip','check'],capture_output=True,text=True)
    assert checked.returncode==0
    report={'created_at':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),'executable':sys.executable,
            'startup_command':'run-seomu.bat --port 8771 --no-browser','installation':'새 .venv, 동봉 wheel 및 --no-index로 설치',
            'initial_status':status,'initial_active_model':settings['llm']['active'],'pinned_versions':expected,'pip_check':checked.stdout.strip(),
            'manifest_verified':True,'model_runs':[],'travel_runs':[],'scope_notice':'동일 PC의 별도 앱 폴더·새 Python 가상환경·새 DB입니다. 별도 PC·OS 설치 또는 로컬 모델 재다운로드 검증은 아닙니다.'}
    print('Initial zero-case DB, default config, pinned packages and source manifest verified',flush=True)
    for profile in ['local_gemma','local_llama']:
        print('Actual model:',profile,flush=True)
        result=request('/api/local-ai/run',{'profile':profile,'scenario':'travel'})
        save(out/(profile+'_fresh.json'),result);report['model_runs'].append(result)
        assert result['passed']
        print('Model passed:',result['response_model'],result['elapsed_seconds'],flush=True)
    for scenario,amount in [('ordinary',342600),('training',221600),('anomaly',None)]:
        result=request('/api/travel/demo-scenarios/'+scenario+'/prepare',{'new_copy':True})
        assert result['calculation']['result']['estimated_total']==amount
        assert result['demo_report']['passed']
        draft=result['prepared_draft_id'];raw=urllib.request.urlopen(args.url+'/api/travel/drafts/'+draft+'/package',timeout=60).read()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            assert z.testzip() is None;m=json.loads(z.read('manifest.json'))
            assert all(hashlib.sha256(z.read(f['path'])).hexdigest()==f['sha256'] for f in m['files'])
            count=len(z.namelist())
        report['travel_runs'].append({'scenario':scenario,'case_id':result['id'],'draft_id':draft,'estimated_total':amount,'demo_report':result['demo_report'],'zip_files':count,'zip_sha256':hashlib.sha256(raw).hexdigest()})
        (out/(scenario+'_fresh.zip')).write_bytes(raw)
        print('Travel passed:',scenario,amount,count,flush=True)
    failure=request('/api/local-ai/failure-check',{});assert failure['passed'];report['failure_check']=failure
    report['passed']=True
    save(out/'clean-install-report.json',report)
    print('CLEAN VALIDATION PASSED',flush=True)


if __name__=='__main__': main()
