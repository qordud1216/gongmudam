"""Local work calendar. Source deadlines are projections; planning never edits them."""
from __future__ import annotations
from contextlib import contextmanager
from bisect import bisect_left, bisect_right
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Literal
import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from . import adhoc, folders, store, tracker, travel_api

from .runtime_paths import state_root

DB_PATH=state_root()/'data/calendar.db'
KST=timezone(timedelta(hours=9))
router=APIRouter(prefix='/api/calendar',tags=['업무 달력'])
COLORS={'manual':'#39755f','travel':'#456b90','collection':'#a46e24','tracked':'#795f97'}

@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH,timeout=15);c.row_factory=sqlite3.Row
    try:yield c;c.commit()
    except Exception:c.rollback();raise
    finally:c.close()

def initialize():
    with db() as c:c.executescript('''
    CREATE TABLE IF NOT EXISTS calendar_events(id TEXT PRIMARY KEY,version INTEGER NOT NULL,payload TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS calendar_exceptions(event_id TEXT NOT NULL,occurrence TEXT NOT NULL,payload TEXT,PRIMARY KEY(event_id,occurrence));
    CREATE TABLE IF NOT EXISTS calendar_history(id INTEGER PRIMARY KEY,event_id TEXT NOT NULL,kind TEXT NOT NULL,before_json TEXT,after_json TEXT,created_at TEXT NOT NULL);
    ''')

def encode(v):return json.dumps(v,ensure_ascii=False,separators=(',',':'))
def now():return datetime.now(timezone.utc).isoformat()

def stamp(value,all_day):
    try:
        if all_day:
            return date.fromisoformat(value).isoformat()
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.tzinfo is None:raise ValueError('시간대가 필요합니다.')
        return dt.astimezone(KST).isoformat(timespec='seconds')
    except (ValueError,AttributeError):raise ValueError('종일 일정은 날짜, 시간 일정은 시간대가 포함된 ISO 날짜·시간을 입력하세요.')

def instant(value):
    if len(value)==10:return datetime.combine(date.fromisoformat(value),time(),KST)
    return datetime.fromisoformat(value).astimezone(KST)

class Event(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=200)
    start:str
    end:str
    all_day:bool=False
    kind:Literal['event','focus','deadline']='event'
    location:str=Field(default='',max_length=200)
    notes:str=Field(default='',max_length=4000)
    work_kind:Literal['travel','collection','folder','tracked']|None=None
    work_id:str|None=Field(default=None,max_length=100)
    recurrence:Literal['none','daily','weekly','monthly']='none'
    repeat_until:date|None=None
    interval:int=Field(default=1,ge=1,le=30)

    @model_validator(mode='after')
    def valid(self):
        self.title=self.title.strip()
        if not self.title:raise ValueError('일정 제목을 입력하세요.')
        self.start=stamp(self.start,self.all_day);self.end=stamp(self.end,self.all_day)
        start,end=instant(self.start),instant(self.end)
        if not 2000<=start.year<=2100 or not 2000<=end.year<=2101:raise ValueError('2000~2100년 범위의 일정을 입력하세요.')
        if not start<end or end-start>timedelta(days=366 if self.all_day else 31):raise ValueError('종료는 시작 이후여야 하며 종일 366일·시간 일정 31일까지입니다.')
        if bool(self.work_kind)!=bool(self.work_id):raise ValueError('연결할 업무 종류와 ID를 함께 선택하세요.')
        if self.recurrence!='none':
            if not self.repeat_until or not start.date()<=self.repeat_until<=start.date()+timedelta(days=730):raise ValueError('반복 종료일은 시작일부터 최대 2년 안에서 지정하세요.')
        elif self.repeat_until:raise ValueError('반복하지 않는 일정에는 반복 종료일을 지정하지 마세요.')
        return self

    def payload(self):return self.model_dump(mode='json')

class Edit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:int=Field(ge=1)
    scope:Literal['series','occurrence']='series'
    occurrence:str|None=None
    event:Event

class Delete(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:int=Field(ge=1)
    scope:Literal['series','occurrence']='series'
    occurrence:str|None=None

def row(c,key):
    r=c.execute('SELECT * FROM calendar_events WHERE id=? AND deleted=0',(key,)).fetchone()
    if not r:raise HTTPException(404,'일정을 찾지 못했습니다. 달력을 새로고침하세요.')
    return dict(r)|{'event':json.loads(r['payload'])}

def anchors(event,window_start=None,window_end=None):
    start=instant(event['start']);last=date.fromisoformat(event['repeat_until']) if event.get('repeat_until') else start.date()
    mode=event['recurrence'];n=0
    if window_start and mode!='none':
        lower=window_start-(instant(event['end'])-start)
        if mode=='monthly':n=max(0,((lower.year-start.year)*12+lower.month-start.month)//event['interval']-1)
        else:n=max(0,(lower-start).days//(event['interval']*(7 if mode=='weekly' else 1))-1)
    while n<=730:
        if mode=='monthly':
            absolute=start.year*12+start.month-1+n*event['interval'];year,month=divmod(absolute,12)
            if year>last.year+1:break
            try:point=start.replace(year=year,month=month+1)
            except ValueError:n+=1;continue  # 31일은 해당 날짜가 없는 달을 건너뜁니다.
        else:
            point=start+timedelta(days=n*event['interval']*(7 if mode=='weekly' else 1))
        if point.date()>last or (window_end and point>=window_end):break
        yield point.date().isoformat() if event['all_day'] else point.isoformat(timespec='seconds')
        if mode=='none':break
        n+=1

def occurrence_payload(event,original):
    if original not in set(anchors(event)):raise HTTPException(422,'원래 반복 일정의 날짜를 확인하세요.')
    return shifted(event,original)

def shifted(event,original):
    duration=instant(event['end'])-instant(event['start']);end=instant(original)+duration
    return event|{'start':original,'end':end.date().isoformat() if event['all_day'] else end.isoformat(timespec='seconds')}

def href(kind,key):
    from urllib.parse import quote
    safe=quote(key,safe='')
    return {'travel':f'travel.html?case={safe}#settle','collection':f'adhoc.html#job-{safe}','folder':f'folders.html#{safe}','tracked':f'index.html#home'}.get(kind,'')

def work_items():
    items=[]
    with travel_api.db() as c:
        for r in c.execute('SELECT id,trip_json FROM travel_cases'):
            trip=json.loads(r['trip_json']);items.append({'kind':'travel','id':r['id'],'title':f"{trip['destination']} · {trip['purpose']}",'href':href('travel',r['id']),'trip':trip})
    with adhoc.db() as c:
        for r in c.execute('SELECT id,settings FROM jobs'):
            settings=json.loads(r['settings']);items.append({'kind':'collection','id':r['id'],'title':settings['title'],'href':href('collection',r['id']),'settings':settings})
    with folders.db() as c:
        for r in c.execute("SELECT id,json_extract(payload,'$.name') AS name FROM libraries"):
            items.append({'kind':'folder','id':r['id'],'title':r['name'],'href':href('folder',r['id'])})
    for task in tracker._items():
        card=store.get_card(task['card_id'])
        if card:items.append({'kind':'tracked','id':task['id'],'title':task.get('label') or card['title'],'href':href('tracked',task['id'])})
    return items

def validate_work(event):
    if event.get('work_id') and not any(w['kind']==event['work_kind'] and w['id']==event['work_id'] for w in work_items()):raise HTTPException(422,'연결할 업무를 찾지 못했습니다. 업무 목록을 새로 확인하세요.')

@router.get('/work-options')
def options():return {'items':[{k:w[k] for k in ('kind','id','title','href')} for w in work_items()]}

def calendar_event(key,event,source='manual',version=1,original=None):
    editable=source=='manual'
    return dict(id=f'{key}@{original or event["start"]}',title=event['title'],start=event['start'],end=event['end'],allDay=event['all_day'],editable=editable,
        backgroundColor=COLORS[source],borderColor=COLORS[source],extendedProps=dict(source=source,event_id=key,version=version,occurrence=original or event['start'],
        recurrence=event.get('recurrence','none'),kind=event.get('kind','event'),location=event.get('location',''),notes=event.get('notes',''),
        work_href=href(event['work_kind'],event['work_id']) if event.get('work_kind') and event.get('work_id') else '',work_kind=event.get('work_kind'),work_id=event.get('work_id'),interval=event.get('interval',1),repeat_until=event.get('repeat_until')))

def source_events():
    for item in work_items():
        data=[];kind=item['kind']
        if kind=='travel':
            t=item['trip'];data=[('trip',t['start_date'],(date.fromisoformat(t['end_date'])+timedelta(days=1)).isoformat(),item['title'])]
        elif kind=='collection':
            s=item['settings']
            education = adhoc.layout(s)['kind']=='education' and all(field in s for field in ('course','departments','event_date','deadline'))
            if education:
                from . import education_calendar
                with adhoc.db() as c:
                    value=adhoc.view(c,item['id'])
                for stage in education_calendar.stage_events(value):
                    e=dict(title=stage['title'],start=stage['start'],end=stage['end'],all_day=True,kind='deadline',work_kind=kind,work_id=item['id'])
                    event=calendar_event(f'{kind}:{item["id"]}:{stage["tag"]}',e,source=kind,
                                         version=value['version']+value['workflow']['revision'])
                    event['extendedProps'].update(stage['properties'])
                    if stage['properties']['overdue']:event.update(backgroundColor='#8c4338',borderColor='#8c4338')
                    yield event
            fields=[('education','event_date','교육일' if education else '기준일')]
            if not education:fields.insert(0,('deadline','deadline','회신 마감'))
            data=[(tag,s[field],(date.fromisoformat(s[field])+timedelta(days=1)).isoformat(),item['title']+' · '+label) for tag,field,label in fields if s.get(field)]
        for tag,start,end,title in data:
            e=dict(title=title,start=start,end=end,all_day=True,kind='deadline',work_kind=kind,work_id=item['id'])
            event=calendar_event(f'{kind}:{item["id"]}:{tag}',e,source=kind)
            if kind=='collection' and education:event['extendedProps']['education_job']=True
            yield event
    for task in tracker.overview(datetime.now(KST).date())['upcoming']:
        e=dict(title=task['task']+' · '+task['title'],start=task['due'],end=(date.fromisoformat(task['due'])+timedelta(days=1)).isoformat(),all_day=True,kind='deadline',work_kind='tracked',work_id=task['task_id'])
        yield calendar_event(f'tracked:{task["task_id"]}:{task["no"]}',e,source='tracked')

def overlaps(event,start,end):return instant(event['start'])<end and instant(event['end'])>start

def manual_between(start,end,blocking_only=False,skip_key=None):
    with db() as c:
        for r in c.execute('SELECT * FROM calendar_events WHERE deleted=0').fetchall():
            if r['id']==skip_key:continue
            e=json.loads(r['payload']);exceptions={x['occurrence']:x['payload'] for x in c.execute('SELECT * FROM calendar_exceptions WHERE event_id=?',(r['id'],))}
            if not blocking_only or (not e['all_day'] and e['kind']!='deadline'):
                for original in anchors(e,start,end):
                    if original in exceptions:continue
                    occurrence=shifted(e,original)
                    if overlaps(occurrence,start,end):yield r,e,original,occurrence
            for original,payload in exceptions.items():
                if payload:
                    occurrence=json.loads(payload)
                    if blocking_only and (occurrence['all_day'] or occurrence['kind']=='deadline'):continue
                    if overlaps(occurrence,start,end):
                        yield r,e,original,occurrence

def events_between(start,end,limit=10000):
    result=[]
    for r,base,original,occurrence in manual_between(start,end):
        item=calendar_event(r['id'],occurrence,version=r['version'],original=original)
        item['extendedProps']['recurrence']=base['recurrence'];result.append(item)
        if len(result)>limit:raise HTTPException(422,'조회 기간의 일정이 10,000개를 넘습니다. 일·주 보기 등으로 기간을 좁혀 주세요. 일부만 표시하지 않았습니다.')
    for event in source_events():
        if overlaps(event,start,end):
            result.append(event)
            if len(result)>limit:raise HTTPException(422,'조회 기간의 일정이 10,000개를 넘습니다. 일·주 보기 등으로 기간을 좁혀 주세요. 일부만 표시하지 않았습니다.')
    result.sort(key=lambda e:(e['start'],e['id']))
    return result

def range_checked(start,end):
    if not start<end or (end-start).days>93:raise HTTPException(422,'조회 기간은 1~93일로 지정하세요.')
    return datetime.combine(start,time(),KST),datetime.combine(end,time(),KST)

@router.get('/events')
def listing(start:date,end:date):
    initialize();a,b=range_checked(start,end);events=events_between(a,b)
    return {'events':events,'truncated':False,'notice':'대한민국 시간(UTC+09:00) · 교육 일정을 누르면 단계와 자료를 확인하고 마감을 수정할 수 있습니다. 원본 일정 막대는 직접 이동하지 않습니다.'}

def conflicts(event,key=None,original=None):
    series=event.get('recurrence','none')!='none'
    if series:
        with db() as c:exceptions={r['occurrence']:r['payload'] for r in c.execute('SELECT * FROM calendar_exceptions WHERE event_id=?',(key,))} if key else {}
        candidates=[shifted(event,a) for a in anchors(event) if a not in exceptions]
        candidates.extend(json.loads(p) for p in exceptions.values() if p)
    else:candidates=[event]
    candidates=sorted((c for c in candidates if not c['all_day'] and c.get('kind')!='deadline'),key=lambda c:instant(c['start']))
    if not candidates:return []
    starts=[instant(c['start']) for c in candidates];ends=[instant(c['end']) for c in candidates];prefix=[]
    for finish in ends:prefix.append(max(prefix[-1],finish) if prefix else finish)
    start=min(starts);end=max(ends);found=[]
    for r,_,anchor,e in manual_between(start,end,blocking_only=True,skip_key=key if series else None):
        if r['id']==key and anchor==original:continue
        a,b=instant(e['start']),instant(e['end'])
        for index in range(bisect_right(prefix,a),bisect_left(starts,b)):
            if ends[index]<=a:continue
            found.append({'title':e['title'],'start':e['start'],'end':e['end'],'planned_start':candidates[index]['start']})
            if len(found)>=20:return found
    return found

def detail(c,key,original=None):
    r=row(c,key);base=r['event'];explicit=original is not None
    if original is None:
        cancelled={x['occurrence'] for x in c.execute('SELECT occurrence FROM calendar_exceptions WHERE event_id=? AND payload IS NULL',(key,))}
        original=next((a for a in anchors(base) if a not in cancelled),base['start'])
    event=occurrence_payload(base,original)
    exception=c.execute('SELECT payload FROM calendar_exceptions WHERE event_id=? AND occurrence=?',(key,original)).fetchone()
    if exception:
        if exception['payload'] is None:
            if explicit:raise HTTPException(404,'취소한 반복 일정입니다.')
        else:event=json.loads(exception['payload'])
    history=[dict(x) for x in c.execute('SELECT kind,created_at FROM calendar_history WHERE event_id=? ORDER BY id DESC LIMIT 30',(key,))]
    return {'id':key,'version':r['version'],'event':event,'series':base,'occurrence':original,'history':history}

def add_conflicts(value,whole=False):
    event=value['series'] if whole else value['event']|{'recurrence':'none','repeat_until':None}
    return value|{'conflicts':conflicts(event,value['id'],value['occurrence'])}
def record(c,key,kind,before,after):c.execute('INSERT INTO calendar_history(event_id,kind,before_json,after_json,created_at) VALUES(?,?,?,?,?)',(key,kind,encode(before) if before else None,encode(after) if after else None,now()))

@router.get('/events/{key}')
def get_event(key:str,occurrence:str|None=None):
    initialize()
    with db() as c:value=detail(c,key,occurrence)
    return add_conflicts(value)

@router.post('/events',status_code=201)
def create(event:Event):
    initialize();payload=event.payload();validate_work(payload);key=uuid.uuid4().hex
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT count(*) FROM calendar_events WHERE deleted=0').fetchone()[0]>=2000:raise HTTPException(422,'일정은 최대 2,000개입니다. 지난 일정을 정리하세요.')
        c.execute('INSERT INTO calendar_events VALUES(?,?,?,0)',(key,1,encode(payload)));record(c,key,'일정 등록',None,payload);value=detail(c,key)
    return add_conflicts(value,whole=True)

@router.patch('/events/{key}')
def edit(key:str,body:Edit):
    initialize();payload=body.event.payload();validate_work(payload)
    with db() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,key)
        if r['version']!=body.version:raise HTTPException(409,'다른 변경이 있습니다. 일정을 다시 열고 확인하세요.')
        if body.scope=='occurrence':
            if not body.occurrence or r['event']['recurrence']=='none':raise HTTPException(422,'반복 일정의 원래 날짜를 지정하세요.')
            occurrence_payload(r['event'],body.occurrence)
            if payload['recurrence']!='none':raise HTTPException(422,'이번 일정만 수정할 때는 반복을 설정할 수 없습니다.')
            before=detail(c,key,body.occurrence)['event']
            c.execute('INSERT OR REPLACE INTO calendar_exceptions VALUES(?,?,?)',(key,body.occurrence,encode(payload)))
        else:
            if any(payload[f]!=r['event'][f] for f in ('start','recurrence','interval','repeat_until')) and c.execute('SELECT 1 FROM calendar_exceptions WHERE event_id=?',(key,)).fetchone():raise HTTPException(422,'개별 수정·취소가 있는 반복 일정입니다. 반복 규칙·시작일은 유지하고 수정하거나 새 일정을 만드세요.')
            before=r['event'];c.execute('UPDATE calendar_events SET payload=? WHERE id=?',(encode(payload),key))
        c.execute('UPDATE calendar_events SET version=version+1 WHERE id=?',(key,));record(c,key,'이번 일정 수정' if body.scope=='occurrence' else '전체 일정 수정',before,payload)
        original=body.occurrence if body.scope=='occurrence' else None;value=detail(c,key,original)
    return add_conflicts(value,whole=body.scope=='series')

@router.post('/events/{key}/delete')
def delete(key:str,body:Delete):
    initialize()
    with db() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,key)
        if r['version']!=body.version:raise HTTPException(409,'다른 변경이 있습니다. 일정을 다시 열어 확인하세요.')
        if body.scope=='occurrence':
            if not body.occurrence or r['event']['recurrence']=='none':raise HTTPException(422,'반복 일정의 원래 날짜를 지정하세요.')
            before=detail(c,key,body.occurrence)['event'];c.execute('INSERT OR REPLACE INTO calendar_exceptions VALUES(?,?,NULL)',(key,body.occurrence))
            c.execute('UPDATE calendar_events SET version=version+1 WHERE id=?',(key,))
        else:
            before=r['event'];c.execute('UPDATE calendar_events SET deleted=1,version=version+1 WHERE id=?',(key,))
        record(c,key,'이번 일정 취소' if body.scope=='occurrence' else '일정 삭제',before,None)
    return {'deleted':True}

@router.get('/free-slots')
def free_slots(date:date,minutes:int=Query(default=30,ge=15,le=240)):
    initialize();start=datetime.combine(date,time(9),KST);end=datetime.combine(date,time(18),KST)
    busy=[e for e in events_between(start,end) if not e['allDay'] and e['extendedProps']['kind']!='deadline'];slots=[];point=start
    while point+timedelta(minutes=minutes)<=end:
        finish=point+timedelta(minutes=minutes)
        if not any(overlaps(e,point,finish) for e in busy):slots.append({'start':point.isoformat(timespec='seconds'),'end':finish.isoformat(timespec='seconds')})
        point+=timedelta(minutes=15)
    return {'slots':slots,'notice':'09~18시의 등록된 시간 일정 기준입니다. 종일 출장·외부 캘린더와 상대방 참석 가능 여부는 따로 확인하세요.'}

def ics_text(value):return str(value).replace('\\','\\\\').replace('\r\n','\n').replace('\r','\n').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
def fold(line):
    lines=[];part='';size=0
    for char in line:
        n=len(char.encode('utf-8'))
        if size+n>75:lines.append(part);part=' ';size=1
        part+=char;size+=n
    return '\r\n'.join(lines+[part])

@router.get('/export.ics')
def export(start:date,end:date):
    initialize();a,b=range_checked(start,end);lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Seomu//Work Calendar//KO','CALSCALE:GREGORIAN']
    for e in events_between(a,b):
        props=e['extendedProps'];uid=e['id'] if props['source']=='manual' and props['recurrence']!='none' else props['event_id']
        lines+=['BEGIN:VEVENT','UID:'+ics_text(uid)+'@seomu.local','DTSTAMP:'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'SEQUENCE:'+str(props['version'])]
        for field in ('start','end'):
            label='DTSTART' if field=='start' else 'DTEND'
            lines.append(label+(';VALUE=DATE:'+e[field].replace('-','') if e['allDay'] else ':'+instant(e[field]).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')))
        lines+=['SUMMARY:'+ics_text(e['title']),'DESCRIPTION:'+ics_text(props.get('notes','')),'LOCATION:'+ics_text(props.get('location','')),'END:VEVENT']
    lines+=['END:VCALENDAR']
    return Response(('\r\n'.join(fold(s) for s in lines)+'\r\n').encode('utf-8'),media_type='text/calendar; charset=utf-8',headers={'Content-Disposition':'attachment; filename="seomu-calendar.ics"'})
