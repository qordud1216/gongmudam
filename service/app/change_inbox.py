"""Cross-library review inbox. All work-level decisions share the library transaction."""
from __future__ import annotations
import copy,json
from typing import Literal
from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import JSONResponse,Response
from pydantic import Field
from . import folders,folder_ai

router=APIRouter(prefix='/api/folders',tags=['변경 알림함'])
MAX_RUNS=1000
class Review(folders.Version):
    target:str=Field(min_length=1,max_length=50)
    action:Literal['seen','apply','defer','reopen']
    revision:int=Field(ge=0)
    file_ids:list[str]|None=Field(default=None,max_length=12)
    apply_notes:bool=True

def targets(result):
    return list(dict.fromkeys([a['project'] for a in result.get('assignments',[])]+[p['project'] for p in result.get('projects',[])]))
def expected_version(r):return r.get('review_version',r['base_version'])
def obsolete(r,v):return (expected_version(r)!=v['version'] or r.get('analysis_contract')!=folder_ai.ANALYSIS_CONTRACT) and not r.get('applied')
def target_name(target,r,v):
    if target=='review':return '분류 확인함'
    if target=='common':return '공통 자료'
    if target.startswith('new:'):return '새 업무 · '+r.get('review_result',r.get('result',{})).get('new_projects',{}).get(target[4:],target)
    return v['projects'].get(target,{}).get('name','이전 업무 · '+target)
def result_of(r):return r.get('review_result',r.get('result',{}))
def group_state(r,target,v):
    saved=r.get('reviews',{}).get(target,{}).get('state')
    if saved in ('applied','deferred'):return saved
    if r.get('applied'):return 'applied'
    if r.get('dismissed'):return 'deferred'
    if r['status']!='completed':return r['status']
    if obsolete(r,v):return 'stale'
    return saved or 'pending'
def card(r,v,target):
    result=result_of(r);assignments=[a for a in result.get('assignments',[]) if a['project']==target]
    note=next((p for p in result.get('projects',[]) if p['project']==target),None)
    members=set(a['file_id'] for a in assignments)
    if note:
        for claim in [note['summary'],*note['actions']]:members.update(e['file_id'] for e in claim['evidence'])
    documents=[d for d in r['input']['documents'] if d['file_id'] in members]
    return dict(library_id=v['id'],library_name=v['name'],library_version=v['version'],run_id=r['id'],target=target,work_name=target_name(target,r,v),
                status=group_state(r,target,v),stale=obsolete(r,v),revision=r.get('review_revision',0),created_at=r['created_at'],model=r.get('model'),trigger=r.get('trigger','manual'),
                file_count=len(documents),file_names=[d['name'] for d in documents],changed_files=[x for x in r.get('changes',[]) if x['file_id'] in members],
                assignment_count=len(assignments),note_count=int(note is not None),protected_count=sum(bool(a.get('protected')) for a in assignments),
                review=r.get('reviews',{}).get(target),history=[h for h in r.get('review_history',[]) if h['target']==target],error=r.get('error'),source_url=f"/folders.html?v=27#{v['id']}")

def listing(status='pending',library_id='',query='',offset=0,limit=30):
    entries=[];libraries={};counts={k:0 for k in ('pending','reviewing','applied','deferred','stale','queued','running','failed','interrupted')}
    with folders.db() as c:
        total=c.execute('SELECT COUNT(*) FROM folder_ai_runs').fetchone()[0]
        rows=c.execute('SELECT library_id,payload FROM folder_ai_runs ORDER BY rowid DESC LIMIT ?',(MAX_RUNS,)).fetchall()
        for row in rows:
            key=row['library_id']
            if key not in libraries:libraries[key]=folders.get(c,key)
            v=libraries[key];r=json.loads(row['payload'])
            for target in targets(result_of(r)) or ['__run__']:
                entry=card(r,v,target)
                if target=='__run__':entry.update(work_name='분석 실행 기록',file_count=r['input']['selected_files'],file_names=[d['name'] for d in r['input']['documents']],status=r['status'] if r['status']!='completed' else 'stale')
                if library_id and key!=library_id:continue
                if query and query.casefold() not in ' '.join([v['name'],entry['work_name'],*entry['file_names']]).casefold():continue
                counts[entry['status']]+=1
                if status=='all' or status=='pending' and entry['status'] in ('pending','reviewing') or status==entry['status']:entries.append(entry)
    return dict(items=entries[offset:offset+limit],total=len(entries),offset=offset,limit=limit,counts=counts,
                libraries=[dict(id=k,name=v['name']) for k,v in libraries.items()],scanned_runs=min(total,MAX_RUNS),total_runs=total,truncated=total>MAX_RUNS)
@router.get('/change-inbox')
def inbox(status:Literal['all','pending','reviewing','applied','deferred','stale','queued','running','failed','interrupted']='pending',library_id:str='',query:str=Query(default='',max_length=150),offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100)):
    return JSONResponse(listing(status,library_id,query,offset,limit),headers={'Cache-Control':'no-store'})
@router.get('/change-inbox/report.json')
def report():
    # Deliberately covers the same bounded scope as the UI, with explicit coverage metadata.
    data=listing('all',limit=100000)
    return Response(folders.encode(data),media_type='application/json',headers={'Content-Disposition':'attachment; filename="change-inbox-report.json"','Cache-Control':'no-store'})
@router.get('/change-inbox/{key}/{rid}')
def detail(key:str,rid:str,target:str):
    with folders.db() as c:
        v=folders.get(c,key);r=folder_ai.stored(c,key,rid);result=result_of(r)
        if target not in targets(result):raise HTTPException(404,'업무별 제안이 없습니다.')
        entry=card(r,v,target);assignments=[copy.deepcopy(a) for a in result.get('assignments',[]) if a['project']==target]
        for a in assignments:
            f=v['files'].get(a['file_id'],{});a['protected']=bool(f.get('manual') or f.get('confirmed'));a['current_projects']=[v['projects'].get(pid,{}).get('name',pid) for pid in f.get('project_ids',[])];a['name']=f.get('name',a['file_id']);a['current_bucket']=f.get('bucket','review')
        previous=r.get('previous_state')
        if previous is None and not entry['stale'] and not r.get('applied') and not r.get('reviews'):previous={'projects':v['projects']}
        old=(previous or {}).get('projects',{}).get(target,{}).get('ai_note',{})
        note=next((p for p in result.get('projects',[]) if p['project']==target),None)
        comparison=folder_ai.change_comparison({'previous_state':previous or {},'changes':r.get('changes',[])},dict(assignments=assignments,projects=[note] if note else []))
        try:folder_ai.verify_sources([v['files'][d['file_id']] for d in r['input']['documents']])
        except (HTTPException,KeyError) as exc:entry.update(stale=True,source_error=str(getattr(exc,'detail','원본 파일을 다시 확인하세요.')))
        entry.update(assignments=assignments,proposed_note=note,before_note=old,comparison=comparison,previous_state_available=previous is not None,
                     roots=v['roots'],analysis_scope=dict(selected=r['input']['selected_files'],eligible=r['input']['eligible_files'],partial=any(d.get('partial') for d in r['input']['documents'])),analysis_issues=result.get('issues',[]),
                     history=[h for h in r.get('review_history',[]) if h['target']==target],
                     report_url=f"/api/folders/libraries/{key}/ai-runs/{rid}/report.json")
        return JSONResponse(entry,headers={'Cache-Control':'no-store'})
@router.post('/change-inbox/{key}/{rid}/review')
def review(key:str,rid:str,body:Review):
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE');v=folders.get(c,key);r=folder_ai.stored(c,key,rid)
        if v['version']!=body.version or r.get('review_revision',0)!=body.revision:raise HTTPException(409,'다른 검토 또는 자료 변경이 있습니다. 최신 알림을 다시 여세요.')
        result=result_of(r);all_targets=targets(result)
        if body.target not in all_targets or r['status']!='completed':raise HTTPException(422,'완료된 업무별 제안만 검토할 수 있습니다.')
        if r.get('applied') or r.get('dismissed'):raise HTTPException(409,'이미 전체 처리한 분석입니다. 새 자료로 재분석하세요.')
        reviews=r.setdefault('reviews',{});prior=reviews.get(body.target,{}).get('state','pending')
        if prior=='applied':raise HTTPException(409,'이미 적용한 업무입니다.')
        if body.action!='defer' and obsolete(r,v):raise HTTPException(409,'분석 이후 자료가 변경되었습니다. 최신 자료로 재분석하세요.')
        if body.action in ('apply','seen') and prior=='deferred':raise HTTPException(409,'보류 업무는 다시 검토를 눌러 여세요.')
        if body.action=='reopen' and prior!='deferred':raise HTTPException(409,'보류한 업무만 다시 검토할 수 있습니다.')
        if body.action=='apply':
            try:validated=folder_ai.validate_saved_result(r,v)
            except ValueError:raise HTTPException(422,'현재 분석 검사를 통과하지 못했습니다. 자료함에서 다시 분석하세요.') from None
            scoped=copy.deepcopy(validated);scoped['assignments']=[a for a in scoped['assignments'] if a['project']==body.target];scoped['projects']=[p for p in scoped['projects'] if p['project']==body.target]
            allowed={a['file_id'] for a in scoped['assignments']}
            selected=body.file_ids if body.file_ids is not None else [a['file_id'] for a in scoped['assignments'] if not a['protected']]
            if any(fid not in allowed for fid in selected):raise HTTPException(422,'다른 업무의 파일을 함께 적용할 수 없습니다.')
            folder_ai.apply_locked(c,v,r,folder_ai.Apply(version=body.version,file_ids=selected,apply_notes=body.apply_notes),result=scoped,finalize=False)
            r['review_version']=v['version']
        decision='applied' if body.action=='apply' else 'deferred' if body.action=='defer' else 'reviewing'
        if not r.get('review_result'):r['review_result']=copy.deepcopy(result)
        reviews[body.target]=dict(state=decision,at=folders.stamp(),action=body.action)
        r['review_revision']=r.get('review_revision',0)+1
        r['review_complete']=all(reviews.get(t,{}).get('state') in ('applied','deferred') for t in all_targets)
        r['review_history']=(r.get('review_history',[])+[dict(target=body.target,action=body.action,at=folders.stamp(),library_version=v['version'],revision=r['review_revision'],file_ids=selected if body.action=='apply' else body.file_ids,apply_notes=body.apply_notes)])[-500:]
        c.execute('UPDATE folder_ai_runs SET payload=? WHERE id=?',(folders.encode(r),rid))
        return dict(library_version=v['version'],revision=r['review_revision'],review_complete=r['review_complete'],review=reviews[body.target])
