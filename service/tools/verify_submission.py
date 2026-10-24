"""Actual two-model checks of the portable app; never count source fallback as model success."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import sqlite3
import sys
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--profiles',nargs='+',default=['local_gemma','local_llama'])
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if not (ROOT/'data/submission-installation.json').exists():raise SystemExit('Restore a separate submission installation first')
    from fastapi.testclient import TestClient
    import httpx
    from app import main as api,config,llm,local_ai,folders,folder_ai,knowledge,regulation_registry
    from tools.audit_question_relevance import evaluate_case
    from tools.check_question_answers import load_sources,DEFAULT_MANIFEST
    from tools.configure_submission_model import configure
    verified,problems=load_sources(DEFAULT_MANIFEST)
    if problems:raise ValueError(problems)
    cases={c['id']:c for name in ('question_checks_v39.json','question_checks_v40.json')
           for c in json.loads((ROOT/'reference_data'/name).read_text(encoding='utf-8'))}
    selected=['domestic-seoul','domestic-daily','sick-01','지방공무원-marriage','budget-01','inspection-deadline','sibling-marriage']
    installed=httpx.get('http://127.0.0.1:11434/api/tags',timeout=5).json()
    report=dict(created_at=datetime.now(timezone.utc).isoformat(),python=platform.python_version(),
        scope='Same PC, separate relocated app folder + new venv and DB; actual installed Ollama models. A second physical PC was not tested.',
        model_environment=installed,runs=[],comparisons=[],shared_checks=[],
        distinctions='Model response, verified model quote, and final source-grounded answer are separate checks. Calculations and workflow edits run in deterministic app code.')
    original_config=(ROOT/'config.json').read_bytes()
    report_path=out/'latest-core-results.json'
    def checkpoint():save(report_path,report)
    with TestClient(api.app) as client:
        def req(method,path,body=None,status=200,**kwargs):
            response=client.request(method,path,json=body,**kwargs)
            if response.status_code!=status:raise ValueError((method,path,response.status_code,response.text[:500]))
            return response
        sources=req('GET','/api/knowledge/sources').json()
        expected=json.loads((ROOT/'submission-data/knowledge.json').read_text(encoding='utf-8'))['sources']
        assert {s['id'] for s in sources}=={s['id'] for s in expected}
        assert all(s['current'] for s in sources) and len(sources)==len(expected)
        assert all(Path(s['path']).is_relative_to(ROOT) for s in sources)
        report['restored_sources']=len(sources)
        report['restored_source_ids_and_hashes']=sorted((s['id'],s['sha256']) for s in sources)
        library=sources[0]['library_id']
        try:
            for name in args.profiles:
                profile=local_ai.local_profile(name)
                print('MODEL '+profile['model'],flush=True)
                # Cold-load latency is recorded separately, not a successful scenario.
                warm=time.perf_counter()
                warm_response=httpx.post('http://127.0.0.1:11434/api/generate',json={'model':profile['model'],'prompt':'','stream':False,'keep_alive':'10m'},timeout=180)
                warm_response.raise_for_status()
                report.setdefault('warmups',[]).append(dict(profile=name,seconds=round(time.perf_counter()-warm,3)))
                configure(ROOT,name,profile['base_url'],profile['model'],json_object=True)
                for cid in selected:
                    case=cases[cid];started=time.perf_counter()
                    with llm.capture_calls() as calls:
                        result=api.api_ask(dict(query=case['question'],knowledge_library_id=library,today='2026-10-21'))
                    evaluation=evaluate_case(case,result,verified)
                    actual=bool(calls) and all(c['response'].get('model')==profile['model'] for c in calls)
                    model_quote=result.get('mode')=='source_llm'
                    expected_call=case['outcome']=='answer'
                    run=dict(kind='registered_source_qa',profile=name,model=profile['model'],case=case,
                        seconds=round(time.perf_counter()-started,3),actual_model_response=actual,
                        verified_model_quote=model_quote,grounded_answer_passed=evaluation['passed'],
                        passed=evaluation['passed'] and (actual and model_quote if expected_call else not calls),
                        evaluation=evaluation,result=result,model_calls=calls)
                    # A missing-source scenario should deliberately skip model generation.
                    run['expected_model_call']=case['outcome']=='answer'
                    report['runs'].append(run);save(out/(name+'-'+cid+'.json'),run);checkpoint()
                    print(cid+' '+result['mode']+' app='+str(run['passed'])+' actual='+str(actual),flush=True)
                for scenario in ('travel','leave','purchase'):
                    run=local_ai.run(local_ai.Run(profile=name,scenario=scenario))
                    report['runs'].append(dict(kind='procedure',profile=name,model=profile['model'],case=scenario,
                                              passed=run['passed'],actual_model_response=run['checks']['actual_model_response'],result=run))
                    save(out/(name+'-procedure-'+scenario+'.json'),run);checkpoint()
                    print('procedure '+scenario+' '+str(run['passed']),flush=True)
                # No explicit 업무명: literal evidence must support proposed classification/summary/action.
                fixture=ROOT/'data/verification-fixtures'/name;fixture.mkdir(parents=True,exist_ok=True)
                (fixture/'준비메모.txt').write_text('오는 2026년 11월 6일 어르신 스마트폰 수업을 준비합니다.\n참석자 회신이 아직 취합되지 않아 명단 확인이 필요합니다.',encoding='utf-8')
                lib=req('POST','/api/folders/libraries',dict(name='[합성 제출 검증] '+name,roots=[str(fixture)]),201).json()
                started=req('POST',f"/api/folders/libraries/{lib['id']}/ai-runs",dict(version=lib['version'],profile=name),202).json()
                run=req('GET',f"/api/folders/libraries/{lib['id']}/ai-runs/{started['id']}").json()
                with folders.db() as c:raw=folder_ai.stored(c,lib['id'],run['id'])
                result=run.get('result',{})
                checks=dict(actual_model=bool(run.get('actual_response')) and run.get('response_model')==profile['model']
                    and all(a.get('actual_response') and a.get('response_model')==profile['model'] for a in raw.get('model_attempts',[])),
                    completed=run['status']=='completed',classification=bool(result.get('assignments')),
                    summary=bool(result.get('projects')),next_actions=any(p.get('actions') for p in result.get('projects',[])),
                    proposal_only=req('GET',f"/api/folders/libraries/{lib['id']}").json()['version']==lib['version'])
                record=dict(kind='document_classification',profile=name,model=profile['model'],passed=all(checks.values()),
                    actual_model_response=checks['actual_model'],checks=checks,result=run,raw_model_response=raw.get('response_text'),
                    model_input=raw.get('input'),request_sha256=raw.get('request_sha256'),response_sha256=raw.get('response_sha256'))
                record['model_attempts']=raw.get('model_attempts',[])
                report['runs'].append(record);save(out/(name+'-folder.json'),record);checkpoint()
                print('folder '+str(record['passed'])+' '+str(run.get('error','')),flush=True)
                # Twelve amount/basis checks use the same installed rule pack.
                case=req('POST','/api/travel/cases',dict(organization_id='national-general',work_pattern='일반근무',destination='부산',purpose='[합성 제출 검증] 회의',start_date='2026-10-15',end_date='2026-10-17',transport='철도',overnight=True,meals_provided=False),201).json()
                case=req('POST',f"/api/travel/cases/{case['id']}/evidence",dict(version=case['version'],source_type='receipt_text',text='2026-10-15 코레일 100원\n2026-10-15 합성호텔 240,000원')).json()
                for row in case['review']['transactions'][:]:
                    case=req('PATCH',f"/api/travel/cases/{case['id']}/transactions/{row['id']}",dict(version=case['version'],decision='include',category=row['category'],reason='합성 영수증 원문을 대조하여 포함')).json()
                amounts=[]
                for grade in ('group1','group2'):
                    for region,cap in (('seoul',200000),('metropolitan',160000),('other',140000)):
                        for vehicle,day in (([],75000),(['2026-10-16'],62500)):
                            total=100+day+75000+(240000 if grade=='group1' else cap)
                            case=req('POST',f"/api/travel/cases/{case['id']}/calculate",dict(version=case['version'],grade=grade,group1_standard_confirmed=grade=='group1',conditions_confirmed=True,ordinary_fare_confirmed=True,lodging_scope_confirmed=True,vehicle_dates=vehicle,lodging_nights=[dict(night='2026-10-15',region=region),dict(night='2026-10-16',region=region)])).json()
                            result=case['calculation']['result']
                            checks=dict(amount=result['estimated_total']==total,basis=all(line['basis'] and all(ref['source_sha256'] for ref in line['basis']) for line in result['lines']))
                            amounts.append(dict(grade=grade,region=region,vehicle_dates=vehicle,expected=total,result=result,passed=all(checks.values())))
                draft=req('POST',f"/api/travel/cases/{case['id']}/drafts",dict(version=case['version']),201).json()
                raw=req('GET',f"/api/travel/drafts/{draft['id']}/package").content
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    assert z.testzip() is None
                    manifest=json.loads(z.read('manifest.json'))
                    assert all(hashlib.sha256(z.read(f['path'])).hexdigest()==f['sha256'] for f in manifest['files'])
                (out/(name+'-travel-draft.zip')).write_bytes(raw)
                record=dict(kind='travel_calculation',profile=name,model=profile['model'],model_called=False,
                    passed=all(r['passed'] for r in amounts),checks=amounts,case_id=case['id'],draft_id=draft['id'])
                report['runs'].append(record);checkpoint();print('travel amounts '+str(record['passed']),flush=True)
        finally:
            (ROOT/'config.json').write_bytes(original_config)
        # Existing end-to-end education scripts run against an isolated loopback server, separately.
        report['failure_check']=local_ai.failure_check()
        assert report['failure_check']['passed']
        for cid in selected:
            pair=[r for r in report['runs'] if r['kind']=='registered_source_qa' and r['case']['id']==cid]
            normalized=[[(e['source_id'],e['sha256'],e['quote']) for e in r['result']['knowledge']['evidence']] for r in pair]
            report['comparisons'].append(dict(case=cid,same_final_sources=all(n==normalized[0] for n in normalized),
                same_displayed_answer=len({r['result']['answer'] for r in pair})==1))
        report['passed']=all(r['passed'] for r in report['runs']) and all(c['same_final_sources'] and c['same_displayed_answer'] for c in report['comparisons'])
        response_count=sum(len(r.get('model_calls',[])) if r['kind']=='registered_source_qa'
            else len(r['result'].get('model_calls',[])) if r['kind']=='procedure'
            else sum(bool(a.get('actual_response')) for a in r.get('model_attempts',[])) if r['kind']=='document_classification'
            else 0 for r in report['runs'])
        report['summary']=dict(actual_model_runs=sum(bool(r.get('actual_model_response')) for r in report['runs']),
            actual_model_responses=response_count,
            verified_model_qa_quotes=sum(bool(r.get('verified_model_quote')) for r in report['runs']),
            app_runs=len(report['runs']),passed=sum(r['passed'] for r in report['runs']),
            expected_qa_model_calls=sum(r.get('expected_model_call',False) for r in report['runs']))
        checkpoint();print(json.dumps(report['summary'],ensure_ascii=False),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
