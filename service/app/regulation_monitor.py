"""출장정산 공식 기준의 정기 확인·기간 연장·변경 검토 API."""
from datetime import timedelta
from pathlib import Path
from typing import Literal
import copy, json, threading
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from . import regulation_registry as registry, regulation_sources as sources, travel_validity

ROOT=Path(__file__).resolve().parents[1]
router=APIRouter(prefix='/api/regulations',tags=['여비 기준 정기 확인'])

def readonly():return (ROOT/'public-demo.json').is_file()

def writable():
    if readonly():raise HTTPException(403,'공개 시연은 규정 확인·검토 설정을 변경할 수 없습니다.')

def base_bundle():
    from . import travel_calculator as calculator
    raw=calculator.BUNDLE_PATH.read_bytes();return registry.sha(raw),json.loads(raw)

def current_bundle():
    base,pack=base_bundle();return base,registry.active_bundle(base) or pack

def renewed(pack,day,key,manifest_sha):
    p=copy.deepcopy(pack)
    if day<p['verified_through']:return p
    if day>p['verified_through']:
        p.update(version=f'{day}.auto.{key[:8]}',verified_through=day)
        p['validity_policy']['reviewed_on']=day
        # Future previews retain the reviewed horizon. This certificate extends only completed dates.
        for s in p['sources'].values():s['verified_on']=day
    p['verification_certificate']=dict(run_id=key,manifest_sha256=manifest_sha,checked_on=day,mode='all_sources_unchanged')
    return p

def renew_cases(pack):
    """확인 기간만 다른 동일 기준의 완료 출장만 갱신. 이전 계산·초안은 불변."""
    from . import travel_api, travel_calculator as calculator
    if not travel_api.DB_PATH.is_file():return []
    changed=[]
    with travel_api.db() as c:
        c.execute('BEGIN IMMEDIATE')
        for row in c.execute('SELECT case_id,snapshot FROM travel_case_legalpacks').fetchall():
            old=json.loads(row['snapshot']);case=travel_api.get_case(c,row['case_id']);trip=case['trip_json']
            if registry.signature(old)!=registry.signature(pack) or not old['verified_through']<trip['end_date']<=pack['verified_through']:continue
            if registry.holds(old,trip):continue
            fresh={**pack,'profile':old['profile']}
            fresh['bundle_sha256']=registry.sha(registry.dumps({k:v for k,v in pack.items() if k!='bundle_sha256'}).encode())
            selected=[r for r in calculator.searchable_rules(fresh) if r['effective_date']<=trip['start_date']]
            travel_api.bump(c,case['id'],case['version'])
            c.execute('UPDATE travel_case_legalpacks SET snapshot=? WHERE case_id=?',(travel_api.dumps(fresh),case['id']))
            c.execute('UPDATE travel_cases SET rule_snapshot=? WHERE id=?',(travel_api.dumps(selected),case['id']))
            travel_api.event(c,case['id'],'LEGAL_PACK_AUTO_REFRESHED',dict(from_version=case['version'],to_version=case['version']+1,
                previous_verified_through=old['verified_through'],verified_through=pack['verified_through'],certificate=pack.get('verification_certificate'),
                reason='모든 공식 원문·현행 버전이 동일함을 확인하여 확인 기간만 연장. 실제 출장 조건 확인 후 재계산 필요.'))
            changed.append(case['id'])
    return changed

def execute(key):
    base,pack=current_bundle()
    try:
        checked=sources.compare(pack)
        day=travel_validity.today()
        if checked['changes']:status='changed';summary=f"공식 자료 {len(checked['changes'])}종의 변경을 발견했습니다. 확인 기간 갱신을 보류했습니다."
        elif not checked['complete']:status='failed';summary='일부 공식 원문을 확인하지 못했습니다. 확인 기간을 유지하고 1시간 후 재시도합니다.'
        else:status='unchanged';summary=f"기준 {len(pack['sources'])}종과 현행 연결을 모두 대조했습니다. 변경이 없습니다."
        manifest_sha=registry.sha(registry.dumps(checked['records']).encode())
        result=dict(status=status,summary=summary,verified_through=pack['verified_through'],manifest_sha256=manifest_sha,**checked)
        result['nonmaterial_reviews']=sources.nonmaterial_reviews(pack,registry.change_rows(),checked)
        if checked['errors']:result['error']='; '.join(checked['errors'])
        new=renewed(pack,day,key,manifest_sha) if status=='unchanged' else None
        # If the installed baseline changed while the network was running, recheck against that baseline.
        if base_bundle()[0]!=base:raise ValueError('확인 중 배포 기준이 바뀌었습니다. 새 배포본으로 다시 확인해야 합니다.')
        result=registry.finish(key,base,pack,result,new)
        if result['status']=='unchanged':
            _,active=current_bundle()
            refreshed=renew_cases(active)
            result.update(verified_through=active['verified_through'],refreshed_cases=refreshed)
            with registry.db() as c:c.execute('UPDATE runs SET result_json=? WHERE id=?',(registry.dumps(result),key))
        return result
    except Exception as e:
        result=dict(status='failed',summary='정기 확인을 완료하지 못했습니다. 확인 기간을 늘리지 않습니다.',error=str(e)[:800],verified_through=pack['verified_through'])
        # Preserve an already committed certificate; a subsequent same-content run retries case refresh.
        with registry.db() as c:
            row=c.execute('SELECT status FROM runs WHERE id=?',(key,)).fetchone()
        if row and row['status']=='running':registry.finish(key,base,pack,result)
        else:
            result['summary']='원문 확인 후 출장 갱신에 실패했습니다. 다음 실행에서 출장 갱신을 재시도합니다.'
            with registry.db() as c:
                c.execute('UPDATE runs SET status=?,result_json=? WHERE id=?',('failed',registry.dumps(result),key))
                c.execute('UPDATE settings SET next_check_at=? WHERE id=1',((registry.now()+timedelta(hours=1)).isoformat(),))
        return result

def run_due(force=False,background=False,internal=False):
    if not internal:writable()
    key,claimed=registry.claim(force)
    if not claimed:return dict(run_id=key,status='already_running_or_not_due')
    if background:
        threading.Thread(target=execute,args=(key,),daemon=True,name='regulation-check').start()
        return dict(run_id=key,status='running')
    return dict(run_id=key,**execute(key))

class Worker:
    def __init__(self):self.stopped=threading.Event();self.thread=None
    def start(self):
        self.thread=threading.Thread(target=self.loop,daemon=True,name='regulation-monitor');self.thread.start();return self
    def loop(self):
        while not self.stopped.is_set():
            try:run_due(background=True,internal=True)
            except Exception:pass # The persistent run record contains source failures; retry on next tick.
            self.stopped.wait(60)
    def stop(self):self.stopped.set()

def affected(item):
    from . import travel_api
    if not travel_api.DB_PATH.is_file():return []
    result=[]
    with travel_api.db() as c:
        for row in c.execute('SELECT case_id,snapshot FROM travel_case_legalpacks'):
            p=json.loads(row['snapshot']);case=travel_api.get_case(c,row['case_id']);trip=case['trip_json']
            if registry.resolved_nonmaterial(item,p):continue
            # Fingerprint includes all fixed calculation inputs; changes for this baseline apply to its date-only renewals too.
            if registry.signature(p)!=item['signature']:continue
            relevant=[s for s in item['sources'] if s['source_id'] in p['profile']['source_ids'] and (not s.get('effective_date') or trip['end_date']>=s['effective_date'])]
            if not relevant:continue
            result.append(dict(id=case['id'],organization=case['profile_snapshot']['name'],destination=trip['destination'],purpose=trip['purpose'],
                start_date=trip['start_date'],end_date=trip['end_date'],case_version=case['version'],scope='potential',
                has_calculation=bool(c.execute('SELECT 1 FROM travel_calculations WHERE case_id=? LIMIT 1',(case['id'],)).fetchone()),
                drafts=c.execute('SELECT count(*) FROM travel_drafts WHERE case_id=?',(case['id'],)).fetchone()[0]))
    return result

def change_detail(key):
    item=next((x for x in registry.change_rows() if x['id']==key),None)
    if not item:raise HTTPException(404,'규정 변경 기록이 없습니다.')
    item['resolution_verified']=registry.resolved_nonmaterial(item,current_bundle()[1])
    item['affected']=affected(item);item['affected_count']=len(item['affected'])
    for k in ('detail_json','fingerprint','signature'):item.pop(k,None)
    return item

@router.get('/status')
def status():
    settings=registry.settings();history=registry.runs(1);_,pack=current_bundle()
    return {**settings,'enabled':bool(settings['enabled']),'last_run':history[0] if history else None,
        'active_pack':dict(version=pack['version'],verified_through=pack['verified_through']),
        'open_changes':sum(x['state']!='reviewed' for x in registry.change_rows()),
        'running':bool(history and history[0]['status']=='running'),'public_read_only':readonly(),
        'notice':'서버 실행 중 정기 확인합니다. PC가 꺼져 있으면 다음 실행 때 확인합니다. 원문·시행일이 바뀐 기준은 담당자 검토 후 별도 검증합니다.'}

class Settings(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=1)
    enabled:bool
    interval_hours:Literal[6,12,24,168]

@router.patch('/settings')
def update_settings(body:Settings):
    writable();registry.initialize()
    with registry.db() as c:
        c.execute('BEGIN IMMEDIATE');s=c.execute('SELECT * FROM settings WHERE id=1').fetchone()
        if s['revision']!=body.revision:raise HTTPException(409,'자동 확인 설정이 바뀌었습니다. 최신 상태를 확인하세요.')
        # Re-enabling catches up immediately; ordinary interval edits reschedule from now.
        next_at=registry.stamp() if body.enabled and not s['enabled'] else (registry.now()+timedelta(hours=body.interval_hours)).isoformat()
        c.execute('UPDATE settings SET enabled=?,interval_hours=?,revision=revision+1,next_check_at=? WHERE id=1',(body.enabled,body.interval_hours,next_at))
    return status()

@router.post('/check',status_code=202)
def check():return run_due(force=True,background=True)

@router.get('/runs')
def list_runs(limit:int=20):return dict(runs=registry.runs(max(1,min(limit,50))))

@router.get('/changes')
def list_changes(state:str='all'):
    result=[]
    for row in registry.change_rows():
        if state!='all' and row['state']!=state:continue
        item=change_detail(row['id']);result.append({k:item[k] for k in ('id','title','state','revision','detected_at','summary','affected_count')})
    return dict(changes=result)

@router.get('/changes/{key}')
def get_change(key:str):return change_detail(key)

class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=1)
    action:Literal['review','defer','acknowledge','reopen']
    reason:str=Field(min_length=1,max_length=2000)

@router.post('/changes/{key}/review')
def review_change(key:str,body:Review):
    writable()
    if not body.reason.strip():raise HTTPException(422,'검토 사유를 입력하세요.')
    with registry.db() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM changes WHERE id=?',(key,)).fetchone()
        if not row:raise HTTPException(404,'변경 기록이 없습니다.')
        if row['revision']!=body.revision:raise HTTPException(409,'검토 기록이 바뀌었습니다. 다시 확인하세요.')
        d=json.loads(row['detail_json']);d['history'].append(dict(at=registry.stamp(),action=body.action,reason=body.reason.strip()))
        if body.action=='reopen':d.pop('resolution',None)
        state={'review':'reviewing','defer':'deferred','acknowledge':'reviewed','reopen':'pending'}[body.action]
        c.execute('UPDATE changes SET state=?,revision=revision+1,detail_json=? WHERE id=?',(state,registry.dumps(d),key))
    return change_detail(key)
