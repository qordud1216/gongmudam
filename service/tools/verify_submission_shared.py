"""Reproduce deterministic core flows against a temporary private loopback server."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if not (ROOT/'data/submission-installation.json').exists():raise SystemExit('Run in a separate restored submission installation')
    import httpx
    from tools.check_education_workflow import check as education
    from tools.check_workflow_chat import check as workflow
    from tools.verify_travel_rate_tables import run as rates
    from app import folders
    with folders.db() as c:
        if c.execute("SELECT 1 FROM folder_ai_runs WHERE status IN ('queued','running')").fetchone():
            raise SystemExit('Finish model tests before starting this second app process')
    def save(name,value):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    report=dict(created_at=datetime.now(timezone.utc).isoformat(),host='127.0.0.1',port=port,model_calls=0)
    with (out/'shared-server.log').open('wb') as log:
        server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port),'--log-level','warning'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if server.poll() is not None:raise RuntimeError('Verification server exited')
                try:
                    if httpx.get(f'http://127.0.0.1:{port}/openapi.json',timeout=1).status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.2)
            else:raise RuntimeError('Verification server not ready')
            result=education(port);save('education-workflow-live.json',result)
            report['education_workflow']=dict(passed=result['passed'],completed=result['final']['workflow']['completed_count'])
            result=workflow(port);save('workflow-chat-live.json',result)
            report['workflow_chat']=dict(passed=True,revision=result['revision'],stages=result['order'])
            result=rates(port);save('travel-rate-boundaries.json',result)
            report['travel_rates']=dict(passed=result['passed'],checks=result['checks'],verified_through=result['verified_through'])
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=20) as c:
                response=c.post('/api/travel/cases',json=dict(organization_id='national-general',work_pattern='일반근무',destination='세종',purpose='[합성 제출 검증] 확인기간 복원',start_date='2026-10-21',end_date='2026-10-21',transport='철도',overnight=False,meals_provided=False))
                response.raise_for_status();case=response.json()
                response=c.post(f"/api/travel/cases/{case['id']}/calculate",json=dict(version=case['version'],grade='group2',conditions_confirmed=True,ordinary_fare_confirmed=True,lodging_scope_confirmed=True,travel_scope='inside',within_minutes=240,round_trip_km=3,lodging_nights=[]))
                response.raise_for_status();case=response.json()
                assert case['calculation']['result']['estimated_total']==20000
                report['restored_certificate']=dict(passed=True,trip_date='2026-10-21',expected=20000,result=case)
            report['passed']=True
            save('shared-core-results.json',report)
            print(json.dumps({k:v for k,v in report.items() if k!='restored_certificate'},ensure_ascii=False),flush=True)
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()
    return 0


if __name__=='__main__':raise SystemExit(main())
