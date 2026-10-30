"""통합 첫 화면의 읽기 전용 준비 상태. 모델 응답 성공과 서버 준비를 구분한다."""
from datetime import datetime,timezone
import json
import httpx
from fastapi import APIRouter
from pydantic import BaseModel,Field,ConfigDict
from . import config,store,travel_api,adhoc,folders,travel_workflow,model_status

router=APIRouter(prefix='/api/workspace',tags=['통합 업무 시작'])


class ModelCheck(BaseModel):
    model_config=ConfigDict(extra='forbid')
    selection_id:str=Field(min_length=16,max_length=128)


@router.get('/model-status')
def selected_model_status():
    return model_status.snapshot()


@router.post('/model-check')
def selected_model_check(body:ModelCheck):
    return model_status.check(body.selection_id)


@router.get('/status')
def status():
    cfg=config.load();active=config.active_profile(cfg)
    try:
        from .runtime_paths import no_llm
        if no_llm():raise ValueError("LLM disabled")
        r=httpx.get('http://127.0.0.1:11434/api/tags',timeout=2);r.raise_for_status()
        models=[{'name':m['name'],'digest':m.get('digest')} for m in r.json().get('models',[])]
        available=True
    except (httpx.HTTPError,ValueError,KeyError): available=False;models=[]
    with travel_api.db() as c:
        organizations=c.execute('SELECT count(*) FROM organizations').fetchone()[0]
        cases=c.execute('SELECT count(*) FROM travel_cases').fetchone()[0]
    with folders.db() as c:
        has_sources=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_sources'").fetchone()
        sources=c.execute('SELECT count(*) FROM knowledge_sources WHERE enabled=1').fetchone()[0] if has_sources else 0
    return {'checked_at':datetime.now(timezone.utc).isoformat(),
            'active_model':{'profile':active['_name'],'model':active.get('model'),'offline':active.get('provider')=='offline'},
            'local_server_available':available,'installed_models':models,
            'local_pair_installed':{'gemma':any(m['name']=='gemma3:4b' for m in models),'llama':any(m['name']=='llama3.2:3b' for m in models)},
            'resources':{'documents':len(store.list_documents()),'procedures':len(store.list_cards()),'forms':len(store.list_forms()),'organizations':organizations,'travel_cases':cases,'knowledge_sources':sources},
            'notice':'설치·준비 상태이며 실제 모델 응답 성공을 뜻하지 않습니다. 모델 실제 실행은 로컬 AI 검증 화면에서 확인하세요.'}


@router.get('/recent')
def recent():
    """At most two saved items per work type, with their actual next action.

    No inference, scan, completion, or export is triggered by opening the home.
    All paths are generated from IDs, never from stored user-supplied URLs.
    """
    items=[];totals={}
    with travel_api.db() as c:
        totals['travel']=c.execute('SELECT count(*) FROM travel_cases').fetchone()[0]
        for row in c.execute('SELECT id,updated_at FROM travel_cases ORDER BY updated_at DESC,id DESC LIMIT 2').fetchall():
            view=travel_api.detail(c,row['id'])
            progress=travel_workflow.summarize(view,travel_api.case_drafts(c,row['id'],view))
            trip=view['trip_json']
            items.append(dict(kind='travel',id=row['id'],title=f"{trip['destination']} · {trip['purpose']}",
                status=progress['stage_label'],next_action=progress['next_action'],
                href=f"travel.html?case={row['id']}#settle",updated_at=row['updated_at']))
    with adhoc.db() as c:
        totals['collection']=c.execute('SELECT count(*) FROM jobs').fetchone()[0]
        rows=c.execute('''SELECT j.id,max(j.created_at,
            coalesce((SELECT max(h.created_at) FROM history h WHERE h.job_id=j.id),''),
            coalesce((SELECT max(w.created_at) FROM job_workflow_history w WHERE w.job_id=j.id),'')) AS updated_at
            FROM jobs j ORDER BY updated_at DESC,j.id DESC LIMIT 2''').fetchall()
        for row in rows:
            view=adhoc.view(c,row['id']);workflow=view['workflow']
            if workflow:
                step=next((s for s in workflow['steps'] if s['id']==workflow['next_step_id']),None)
                status=step['status_label'] if step else '진행표 확인 완료'
                next_action=(step['title']+' · '+(step['blockers'][0] if step['blockers'] else '자료 확인 후 완료를 눌러 주세요.')) if step else '저장한 취합본을 열어 결과를 확인하세요.'
            else:
                current=any(e['is_current'] for e in view['exports'])
                status='취합본 저장됨' if current else '취합본 저장 가능' if view['can_finalize'] else '회신·행 검토 필요'
                next_action='저장한 취합본을 확인하세요.' if current else '현재 버전의 취합본을 저장하세요.' if view['can_finalize'] else f"미회신 {view['summary']['missing']}개 부서 · 보류 {view['summary']['pending']}행을 확인하세요."
            items.append(dict(kind='education' if workflow else 'collection',id=row['id'],title=view['settings']['title'],
                status=status,next_action=next_action,href=f"adhoc.html#job-{row['id']}",updated_at=row['updated_at']))
    with folders.db() as c:
        totals['folder']=c.execute('SELECT count(*) FROM libraries').fetchone()[0]
        candidates=[]
        # The payload owns its history time; SQLite row order is not an update time.
        for row in c.execute('SELECT id,payload FROM libraries'):
            payload=json.loads(row['payload'])
            updated_at=max([payload.get('scanned_at','')]+[h.get('at','') for h in payload.get('history',[])])
            candidates.append((updated_at,row['id'],payload))
        for updated_at,key,payload in sorted(candidates,key=lambda v:(v[0],v[1]),reverse=True)[:2]:
            summary=folders.present(payload)['summary'];review=summary['review']
            items.append(dict(kind='folder',id=key,title=payload['name'],status=f'분류 확인 {review}개 남음' if review else '분류 확인됨' if summary['files'] else '폴더 자료 확인 필요',
                next_action=f'분류 제안 {review}개를 확인하고 분석 결과를 저장하세요.' if review else '분석 결과를 저장하고 업무별 다음 할 일을 확인하세요.',
                href=f'folders.html#{key}',updated_at=updated_at))
    items.sort(key=lambda item:(item['updated_at'],item['id']),reverse=True)
    return {'items':items,'totals':totals}
