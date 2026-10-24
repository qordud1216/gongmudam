"""Persistent local scan jobs; one sequential reader, atomic final publication."""
from __future__ import annotations
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from . import folders, folder_inputs, folder_scan_io as reader

router = APIRouter(prefix='/api/folders', tags=['로컬 폴더 순차 분석'])
threads = {}
thread_lock = threading.Lock()


class Start(folders.Connect):
    library_id: str | None = Field(default=None, min_length=1, max_length=100)
    version: int | None = Field(default=None, ge=1)


def initialize(recover=False):
    with folders.db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS folder_scan_jobs(
          id TEXT PRIMARY KEY,status TEXT NOT NULL,payload TEXT NOT NULL);
          CREATE UNIQUE INDEX IF NOT EXISTS one_active_folder_scan ON folder_scan_jobs((1))
          WHERE status IN ('queued','running');''')
        if recover:
            for row in c.execute("SELECT * FROM folder_scan_jobs WHERE status IN ('queued','running')").fetchall():
                v=json.loads(row['payload']);v.update(status='interrupted',error='서버가 재시작되어 분석이 중단됐습니다. 다시 연결·분석하세요.',updated_at=folders.stamp())
                c.execute('UPDATE folder_scan_jobs SET status=?,payload=? WHERE id=?',('interrupted',folders.encode(v),row['id']))


def allowed(request, write=False):
    if write:
        ok = folder_inputs.local_picker_allowed(request)
    else:
        ok = (not getattr(request.app.state,'public_demo',False) and request.client
              and request.client.host in {'127.0.0.1','::1'} and request.url.hostname in {'127.0.0.1','localhost','::1'}
              and not request.headers.get('cf-connecting-ip') and not request.headers.get('x-forwarded-for'))
    if not ok: raise HTTPException(403,'내 PC 직접 분석은 앱이 실행 중인 PC의 localhost에서만 사용할 수 있습니다.')


def get(c, key):
    row=c.execute('SELECT payload FROM folder_scan_jobs WHERE id=?',(key,)).fetchone()
    if not row: raise HTTPException(404,'폴더 분석 작업을 찾지 못했습니다.')
    return json.loads(row['payload'])


def put(c, v):
    v['updated_at']=folders.stamp()
    c.execute('UPDATE folder_scan_jobs SET status=?,payload=? WHERE id=?',(v['status'],folders.encode(v),v['id']))


def public(v):
    return {k:value for k,value in v.items() if k!='input'}


@router.post('/scan-jobs',status_code=202)
def start(body:Start, request:Request):
    allowed(request,True);initialize()
    roots=folders.roots_checked(body.roots)
    if body.library_id and body.version is None:raise HTTPException(422,'재분석할 자료함 버전을 확인하세요.')
    key=uuid.uuid4().hex
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE')
        active=c.execute("SELECT id FROM folder_scan_jobs WHERE status IN ('queued','running')").fetchone()
        if active:raise HTTPException(409,'이미 폴더 분석이 진행 중입니다. 진행 중인 작업을 확인하거나 취소하세요.')
        if body.library_id:
            v=folders.get(c,body.library_id)
            if v['version']!=body.version:raise HTTPException(409,'자료함 내용이 바뀌었습니다. 최신 자료함을 다시 여세요.')
            if v.get('reference_kind')=='system_manual':raise HTTPException(422,'전체 페이지 매뉴얼은 전용 등록 도구로 다시 색인하세요.')
        value=dict(id=key,status='queued',phase='discovering',discovered=0,processed=0,reused=0,failed_files=0,limited_files=0,
                   current_file='',current_bytes=0,total_bytes=0,bytes_read=0,total=None,library_id=None,
                   error='',warnings=[],cancel_requested=False,created_at=folders.stamp(),
                   input=body.model_dump()|{'roots':[str(p) for p in roots]})
        c.execute('INSERT INTO folder_scan_jobs VALUES(?,?,?)',(key,'queued',folders.encode(value)))
    path=Path(folders.DB_PATH)
    worker=threading.Thread(target=run_job,args=(key,path),name='folder-scan-'+key[:8],daemon=True)
    with thread_lock:threads[key]=worker
    worker.start()
    return public(value)


@router.get('/scan-jobs/{key}')
def status(key:str,request:Request):
    allowed(request)
    with folders.db() as c:return public(get(c,key))


@router.post('/scan-jobs/{key}/cancel')
def cancel(key:str,request:Request):
    allowed(request,True)
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE');v=get(c,key)
        if v['status'] in ('queued','running'):
            v['cancel_requested']=True;put(c,v)
        return public(v)


def run_job(key,path):
    try:
        if Path(folders.DB_PATH)!=path:return
        with folders.db() as c:
            c.execute('BEGIN IMMEDIATE')
            value=get(c,key);body=Start(**value['input']);value['status']='running';put(c,value)
            original=folders.get(c,body.library_id) if body.library_id else None
        last_write=0.;last_processed=-1
        def progress(state):
            nonlocal last_write,last_processed
            if Path(folders.DB_PATH)!=path:raise reader.Cancelled()
            now=time.monotonic()
            # Check cancellation at each chunk/entry, persist counters at most 5Hz
            # and after each completed file. No transaction spans filesystem I/O.
            with folders.db() as c:
                c.execute('BEGIN IMMEDIATE')
                current=get(c,key)
                if current['cancel_requested']:raise reader.Cancelled()
                if now-last_write>=.2 or state['processed']!=last_processed or state['phase']=='saving':
                    current.update(state);put(c,current);last_write=now;last_processed=state['processed']
        incoming,warnings=reader.collect(folders.roots_checked(body.roots),previous=original['files'] if original else None,progress=progress)
        with folders.db() as c:
            c.execute('BEGIN IMMEDIATE');value=get(c,key)
            if value['cancel_requested']:raise reader.Cancelled()
            if original:
                latest=folders.get(c,body.library_id)
                if latest['version']!=body.version:raise HTTPException(409,'분석 중 자료함 변경')
                latest['roots']=body.roots;latest['scan_mode']=reader.PROFILE
                folders.propose(latest,incoming,warnings,inventory_complete=not warnings)
                folders.save(c,latest,body.version,'폴더 순차 재분석',{'roots':body.roots,'warnings':warnings,'reused':value['reused']})
                library_id=body.library_id
            else:
                library_id=uuid.uuid4().hex
                v=dict(id=library_id,version=1,name=body.name,situation=body.situation,roots=body.roots,
                       scan_mode=reader.PROFILE,history=[{'at':folders.stamp(),'kind':'폴더 직접 연결·순차 분석','detail':{'roots':body.roots}}])
                folders.propose(v,incoming,warnings)
                c.execute('INSERT INTO libraries VALUES(?,?,?)',(library_id,1,folders.encode(v)))
            value.update(status='completed',phase='saving',library_id=library_id,warnings=warnings);put(c,value)
    except reader.Cancelled:
        finish(key,path,'cancelled','분석을 취소했습니다. 기존 자료함과 분류는 유지됩니다.')
    except Exception as exc:
        error=('분석 중 자료함 내용이 바뀌었습니다. 최신 자료함을 열고 다시 분석하세요.' if isinstance(exc,HTTPException) and exc.status_code==409
               else '폴더 분석에 실패했습니다. 경로·권한·저장 공간을 확인하고 다시 시도하세요.')
        finish(key,path,'failed',error)
    finally:
        with thread_lock:threads.pop(key,None)


def finish(key,path,state,error):
    if Path(folders.DB_PATH)!=path:return
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE')
        v=get(c,key);v.update(status=state,error=error);put(c,v)


def stop():
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE')
        for row in c.execute("SELECT id FROM folder_scan_jobs WHERE status IN ('queued','running')").fetchall():
            v=get(c,row['id']);v['cancel_requested']=True;put(c,v)
    with thread_lock:workers=list(threads.values())
    for worker in workers:worker.join(timeout=2)
