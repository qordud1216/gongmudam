"""Opt-in bounded polling; original documents and accepted AI notes are never written here."""
from __future__ import annotations
import copy,json,threading,time,uuid
from pathlib import Path
from fastapi import APIRouter,HTTPException
from pydantic import Field
from . import folders,folder_ai,local_ai

router=APIRouter(prefix='/api/folders',tags=['폴더 자동 감지'])
class Settings(folders.Strict):
    enabled:bool
    profile:str=Field(min_length=1,max_length=100)
    interval:int=Field(default=30,ge=5,le=3600)

def initialize():
    with folders.db() as c:c.execute('CREATE TABLE IF NOT EXISTS folder_watches(library_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
def state(c,key):
    folders.get(c,key)
    row=c.execute('SELECT payload FROM folder_watches WHERE library_id=?',(key,)).fetchone()
    return json.loads(row['payload']) if row else dict(enabled=False,profile='',interval=30,pending={},changes=[],blocked=False)
def put(c,key,s):c.execute('INSERT OR REPLACE INTO folder_watches VALUES(?,?)',(key,folders.encode(s)))
def public(s):return {k:v for k,v in s.items() if k not in ('candidate','pending')}|{'pending_files':len(s.get('pending',{}))}
@router.get('/libraries/{key}/watch')
def status(key:str):
    with folders.db() as c:return public(state(c,key))
@router.put('/libraries/{key}/watch')
def configure(key:str,body:Settings):
    if body.enabled:local_ai.local_profile(body.profile)
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE');s=state(c,key)
        s.update(**body.model_dump(),blocked=False,error='',next_check=0);s.pop('candidate',None);put(c,key,s)
        return public(s)
@router.post('/libraries/{key}/watch/retry')
def retry(key:str):
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE');s=state(c,key);s.update(blocked=False,error='',next_check=0)
        v=folders.get(c,key)
        if s.get('last_run_id'):
            r=folder_ai.stored(c,key,s['last_run_id'])
            for d in r['input']['documents']:
                f=v['files'].get(d['file_id'])
                if f and f['present'] and f['units']:s['pending'][f['id']]=f['sha256']
        put(c,key,s);return public(s)
@router.post('/libraries/{key}/ai-runs/{rid}/dismiss')
def dismiss(key:str,rid:str,body:folders.Version):
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE');v=folders.get(c,key);r=folder_ai.stored(c,key,rid)
        if v['version']!=body.version:raise HTTPException(409,'최신 자료함을 다시 여세요.')
        if r['status'] not in ('completed','failed','interrupted') or r.get('applied') or r.get('reviews'):raise HTTPException(409,'종료된 미적용 제안만 보류 처리할 수 있습니다.')
        r.update(dismissed=True,dismissed_at=folders.stamp())
        c.execute('UPDATE folder_ai_runs SET payload=? WHERE id=?',(folders.encode(r),rid))
        return folder_ai.view_run(r,v)

def signature(files):
    # Content hashes prevent touching a file from repeatedly consuming model calls.
    return folder_ai.digest({fid:(f.get('sha256') or [f['size'],f['mtime_ns']],f.get('present',True)) for fid,f in sorted(files.items()) if f.get('present',True)})

def scan_one(key,now=None):
    now=time.time() if now is None else now
    with folders.db() as c:
        s=state(c,key);v=folders.get(c,key)
    if not s['enabled'] or now<s.get('next_check',0):return
    try:
        roots=folders.roots_checked(v['roots'])
        if v.get('scan_mode')=='direct-v63':
            from . import folder_scan_io
            incoming,warnings=folder_scan_io.collect(roots,previous=v['files'])
        else:
            incoming,warnings=folders.collect(roots)
        # Incomplete traversal must not turn inaccessible files into removals or partial AI context.
        if warnings:raise ValueError('폴더 읽기 범위·변경 중 파일을 확인하세요: '+'; '.join(warnings[:3]))
        sig=signature(incoming);baseline=signature(v['files']);changed=sig!=baseline
        with folders.db() as c:
            c.execute('BEGIN IMMEDIATE');fresh=state(c,key);current=folders.get(c,key)
            if not fresh['enabled']:return
            fresh.update(last_checked=folders.stamp(),next_check=now+fresh['interval'],scan_error='')
            if current['version']!=v['version']:
                fresh.pop('candidate',None);put(c,key,fresh);return
            if not changed:
                fresh.pop('candidate',None)
                for fid,f in incoming.items():
                    if fid in current['files']:current['files'][fid].update(size=f['size'],mtime_ns=f['mtime_ns'])
                c.execute('UPDATE libraries SET payload=? WHERE id=?',(folders.encode(current),key))
                put(c,key,fresh);return
            if fresh.get('candidate')!=sig:
                fresh['candidate']=sig;put(c,key,fresh);return
            # Two identical bounded reads on separate polling cycles debounce partial writes.
            changes=[]
            for fid,f in incoming.items():
                old=v['files'].get(fid)
                if not old or not old.get('present') or (old['sha256'] or [old['size'],old['mtime_ns']])!=(f['sha256'] or [f['size'],f['mtime_ns']]):
                    changes.append(dict(file_id=fid,name=f['name'],kind='modified' if old and old.get('present') else 'added',before_sha256=old.get('sha256') if old else None,sha256=f['sha256'],at=folders.stamp()))
                    if f['units']:fresh['pending'][fid]=f['sha256']
            for fid,f in v['files'].items():
                if f.get('present') and fid not in incoming:changes.append(dict(file_id=fid,name=f['name'],kind='unavailable',at=folders.stamp()))
            folders.propose(current,incoming,warnings)
            folders.save(c,current,v['version'],'폴더 변경 자동 감지',{'changes':changes})
            fresh['pending']={fid:sha for fid,sha in fresh['pending'].items() if fid in incoming and incoming[fid]['present'] and incoming[fid]['units']}
            fresh['changes']=(fresh.get('changes',[])+changes)[-200:];fresh['last_detected']=folders.stamp();fresh.pop('candidate',None)
            # New content releases a failed batch; unchanged errors require explicit retry.
            fresh.update(blocked=False,error='');put(c,key,fresh)
    except (HTTPException,ValueError,OSError) as exc:
        with folders.db() as c:
            c.execute('BEGIN IMMEDIATE');s=state(c,key);s.update(scan_error=str(getattr(exc,'detail',exc))[:1000],last_checked=folders.stamp(),next_check=now+s['interval']);put(c,key,s)

def reserve():
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM folder_ai_runs WHERE status IN ('queued','running')").fetchone():return
        for row in c.execute('SELECT library_id,payload FROM folder_watches ORDER BY rowid').fetchall():
            key=row['library_id'];s=json.loads(row['payload'])
            if not s['enabled'] or s.get('blocked'):continue
            v=folders.get(c,key)
            # Preserve a reviewable proposal until applied; changed content invalidates it and is requeued.
            previous=c.execute("SELECT payload FROM folder_ai_runs WHERE library_id=? ORDER BY rowid DESC LIMIT 1",(key,)).fetchone()
            if previous:
                r=json.loads(previous['payload'])
                if r.get('trigger')=='watch' and not r.get('applied') and not r.get('dismissed') and not r.get('review_complete'):
                    if r['status']=='completed' and r.get('review_version',r['base_version'])==v['version']:continue
                    if r.get('review_version',r['base_version'])!=v['version'] or r['status']=='interrupted':
                        for d in r['input']['documents']:
                            f=v['files'].get(d['file_id'])
                            if f and f['present'] and f['units']:s['pending'][f['id']]=f['sha256']
            ids=[fid for fid in s['pending'] if fid in v['files'] and v['files'][fid]['present'] and v['files'][fid]['units']][:folder_ai.MAX_DOCUMENTS]
            if not ids:continue
            related={pid for fid in ids for pid in v['files'][fid]['project_ids']}
            context=[f['id'] for f in v['files'].values() if f['present'] and f['units'] and f['id'] not in ids and related.intersection(f['project_ids'])]
            ids=(ids+context)[:folder_ai.MAX_DOCUMENTS]
            try:
                profile=local_ai.local_profile(s['profile']);body=folder_ai.Start(version=v['version'],profile=s['profile'],file_ids=ids)
                data=folder_ai.make_input(v,body)
                changed_ids=set(s['pending'])
                for d in data['documents']:d['watch_role']='changed_document' if d['file_id'] in changed_ids else 'related_context'
                data['watch_notice']='변경 문서와 관련 문맥 자료를 구분한다. 서로 다른 상태 진술은 원문을 대조해 확인할 사항으로 제안하며, 수정 시각만으로 완료를 확정하지 않는다.'
                folder_ai.verify_sources([v['files'][fid] for fid in ids])
            except (HTTPException,ValueError) as exc:
                s.update(blocked=True,error=str(getattr(exc,'detail',exc))[:500]);put(c,key,s);continue
            rid=uuid.uuid4().hex
            r=dict(id=rid,library_id=key,base_version=v['version'],profile=s['profile'],model=profile.get('model'),endpoint=profile['base_url'],status='queued',created_at=folders.stamp(),input=data,applied=False,analysis_contract=folder_ai.ANALYSIS_CONTRACT,trigger='watch',changes=[x for x in s.get('changes',[]) if x['file_id'] in ids][-100:],
                   previous_state={'files':{fid:{k:v['files'][fid].get(k) for k in ('project_ids','bucket','confirmed')} for fid in ids},'projects':copy.deepcopy(v['projects'])})
            c.execute('INSERT INTO folder_ai_runs VALUES(?,?,?,?)',(rid,key,'queued',folders.encode(r)))
            for fid in ids:s['pending'].pop(fid,None)
            s.update(last_run_id=rid,error='');put(c,key,s)
            return rid,key,data,v,profile

def analyze_one():
    job=reserve()
    if not job:return
    rid,key,data,v,profile=job
    folder_ai.execute(rid,key,data,v,profile)
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE');s=state(c,key);r=folder_ai.stored(c,key,rid)
        if r['status']=='failed':
            for d in data['documents']:s['pending'][d['file_id']]=d['sha256']
            s.update(blocked=True,error=r.get('error','AI 분석 실패'))
        put(c,key,s)

class Worker:
    def __init__(self):self.stop_event=threading.Event();self.path=Path(folders.DB_PATH);self.threads=[]
    def start(self):
        for target in (self.scan_loop,self.ai_loop):
            t=threading.Thread(target=target,daemon=True,name='folder-watch');t.start();self.threads.append(t)
        return self
    def stop(self):
        self.stop_event.set()
        for t in self.threads:t.join(timeout=1)
    def scan_loop(self):
        while not self.stop_event.wait(1):
            if Path(folders.DB_PATH)!=self.path:continue
            try:
                with folders.db() as c:keys=[r[0] for r in c.execute('SELECT library_id FROM folder_watches')]
                for key in keys:
                    if self.stop_event.is_set():break
                    scan_one(key)
            except Exception:
                import logging;logging.getLogger(__name__).exception('Folder monitoring cycle failed')
    def ai_loop(self):
        while not self.stop_event.wait(2):
            if Path(folders.DB_PATH)!=self.path:continue
            try:analyze_one()
            except Exception:
                import logging;logging.getLogger(__name__).exception('Folder AI queue cycle failed')
