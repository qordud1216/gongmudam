"""Work agenda and local reminder acknowledgements; never equate an alert with completion."""
from datetime import datetime, date, time, timedelta
import hashlib
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from . import adhoc, calendar_api as calendar, education_calendar, folders, tracker, travel_api

router=APIRouter(prefix='/api/calendar/agenda',tags=['업무 보기·앱 내 마감 알림'])


def now_kst():return datetime.now(calendar.KST)


def initialize():
    with calendar.db() as c:c.executescript('''
    CREATE TABLE IF NOT EXISTS calendar_agenda_settings(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,enabled INTEGER NOT NULL,days INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS calendar_alert_states(key TEXT PRIMARY KEY,state TEXT NOT NULL,until_at TEXT,updated_at TEXT NOT NULL);
    ''')


def preferences(c):
    row=c.execute('SELECT revision,enabled,days FROM calendar_agenda_settings WHERE id=1').fetchone()
    return dict(revision=row['revision'],enabled=bool(row['enabled']),days=row['days']) if row else dict(revision=0,enabled=True,days=3)


def task(key,kind,work_id,work_title,title,due,status,label,action,*,is_deadline=True,is_task=True,deadline_at=None):
    return dict(id=key,kind=kind,work_key=kind+':'+work_id,work_title=work_title,title=title,due=due,
                status=status,status_label=label,action=action,is_deadline=is_deadline,is_task=is_task,deadline_at=deadline_at)


def tasks(now):
    result=[]
    with adhoc.db() as c:
        for row in c.execute('SELECT id FROM jobs').fetchall():
            v=adhoc.view(c,row['id']);title=v['settings']['title']
            if v['workflow']:
                for s in v['workflow']['steps']:
                    result.append(task('education:'+v['id']+':'+s['id'],'collection',v['id'],title,s['title'],s['due_date'],
                        s['status'],s['status_label'],dict(type='education',job_id=v['id'],step_id=s['id'])))
            else:
                # A saved review copy is not a final approval or an explicit completion record.
                label='취합본 저장됨 · 완료 미확인' if any(e['is_current'] for e in v['exports']) else '회신·검토 필요'
                result.append(task('collection:'+v['id'],'collection',v['id'],title,'회신 마감',v['settings']['deadline'],
                    'unknown',label,dict(type='link',href=calendar.href('collection',v['id']))))
    for it in tracker.overview(now.date())['tasks']:
        if it.get('missing'):continue
        for s in it['steps']:
            result.append(task(f"tracked:{it['id']}:{s['no']}",'tracked',it['id'],it['label'] or it['title'],s['title'],s.get('due'),
                'done' if s['done'] else 'todo','완료' if s['done'] else '미완료',dict(type='link',href=calendar.href('tracked',it['id']))))
    with travel_api.db() as c:
        for row in c.execute('SELECT id,trip_json FROM travel_cases'):
            trip=json.loads(row['trip_json']);title=f"{trip['destination']} · {trip['purpose']}"
            result.append(task('travel:'+row['id'],'travel',row['id'],title,'출장정산 처리 확인',None,'unknown','정산 완료 미확인',
                dict(type='link',href=calendar.href('travel',row['id']))))
    with folders.db() as c:
        for row in c.execute('SELECT id,payload FROM libraries'):
            p=json.loads(row['payload'])
            # Empty libraries have no files to review; a nonempty library has no completion flag.
            if not p.get('files'):continue
            result.append(task('folder:'+row['id'],'folder',row['id'],p['name'],'자료 분류·업무 확인',None,'unknown','업무 완료 미확인',
                dict(type='link',href=calendar.href('folder',row['id']))))
    # Limit recurring occurrences, not the dates of one-off deadlines. Never expand years of repeats.
    start=datetime.combine(now.date()-timedelta(days=7),time(),calendar.KST)
    end=datetime.combine(now.date()+timedelta(days=15),time(),calendar.KST)
    with calendar.db() as c:
        for r in c.execute('SELECT id,version,payload FROM calendar_events WHERE deleted=0'):
            event=json.loads(r['payload'])
            if event['recurrence']!='none':continue
            e=calendar.calendar_event(r['id'],event,version=r['version'])
            result.append(manual_task(e,event))
    for r,event,original,occurrence in calendar.manual_between(start,end):
        if event['recurrence']=='none':continue
        e=calendar.calendar_event(r['id'],occurrence,version=r['version'],original=original)
        e['extendedProps']['recurrence']=event['recurrence']
        result.append(manual_task(e,occurrence))
    if len(result)>10000:raise HTTPException(422,'업무 항목이 10,000개를 넘습니다. 보관할 업무를 정리한 뒤 다시 확인하세요. 일부만 전체처럼 표시하지 않았습니다.')
    return result


def manual_task(e,payload):
    props=e['extendedProps'];kind=props.get('work_kind') or 'manual';work_id=props.get('work_id') or props['event_id']
    is_deadline=payload['kind']=='deadline'
    # Appointments remain appointments; a passed meeting is never an overdue task automatically.
    return task('manual:'+e['id'],kind,work_id,e['title'],e['title'],calendar.instant(e['start']).date().isoformat(),
                'unknown','완료 미확인' if is_deadline else '등록 일정',dict(type='manual',event=e),
                is_deadline=is_deadline,is_task=is_deadline,
                deadline_at=None if e['allDay'] else calendar.instant(e['start']).isoformat())


def alert_key(item):
    raw=json.dumps([item['id'],item['due'],item['deadline_at'],item['status']],ensure_ascii=True,separators=(',',':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def snapshot(now=None,include_eligible=False):
    now=now or now_kst();today=now.date();week_start=today-timedelta(days=today.weekday());week_end=week_start+timedelta(days=6)
    with calendar.db() as c:
        prefs=preferences(c);states={r['key']:dict(r) for r in c.execute('SELECT * FROM calendar_alert_states')}
    items=tasks(now);alerts=[];eligible=[]
    for item in items:
        due=date.fromisoformat(item['due']) if item['due'] else None
        active=item['status']!='done'
        item['overdue']=bool(active and item['is_deadline'] and due and (
            calendar.instant(item['deadline_at'])<=now if item['deadline_at'] else due<today))
        item['imminent']=bool(active and item['is_deadline'] and due and not item['overdue'] and today<=due<=today+timedelta(days=prefs['days']))
        item['in_week']=bool(due and week_start<=due<=week_end)
        if prefs['enabled'] and (item['overdue'] or item['imminent']):
            key=alert_key(item)
            alert=dict(key=key,task_id=item['id'],title=item['work_title']+' · '+item['title'],due=item['due'],task=item,
                       level='overdue' if item['overdue'] else 'today' if due==today else 'soon')
            eligible.append(alert)
            state=states.get(key)
            if not state or (state['state']=='snooze' and calendar.instant(state['until_at'])<=now):alerts.append(alert)
    items.sort(key=lambda t:(t['due'] is None,t['due'] or '',t['work_title'],t['id']))
    alerts.sort(key=lambda a:(a['due'],a['task_id']))
    result=dict(now=now.isoformat(),today=today.isoformat(),week_start=week_start.isoformat(),week_end=week_end.isoformat(),
                preferences=prefs,tasks=items,alerts=alerts,
                notice='한국 표준시·월~일 기준입니다. 알림 확인은 업무 완료가 아닙니다. 반복 일정은 지난 7일~향후 14일 회차를 표시합니다. 앱을 열어둔 동안 마감을 확인합니다.')
    if include_eligible:result['_eligible_alerts']=eligible
    return result


class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Preferences(Strict):
    revision:int=Field(ge=0)
    enabled:bool
    days:int=Field(ge=0,le=14)
class AlertAction(Strict):
    key:str=Field(pattern='^[0-9a-f]{64}$')
    action:Literal['read','snooze']


@router.get('')
def overview():return snapshot()


@router.patch('/preferences')
def save_preferences(body:Preferences):
    with calendar.db() as c:
        c.execute('BEGIN IMMEDIATE');current=preferences(c)
        if current['revision']!=body.revision:raise HTTPException(409,'알림 설정이 바뀌었습니다. 최신 정보를 다시 불러와 주세요.')
        c.execute('INSERT INTO calendar_agenda_settings VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,enabled=excluded.enabled,days=excluded.days',
                  (current['revision']+1,int(body.enabled),body.days))
        return preferences(c)


@router.post('/alerts')
def alert_action(body:AlertAction):
    now=now_kst()
    if not any(a['key']==body.key for a in snapshot(now,True)['_eligible_alerts']):
        raise HTTPException(409,'마감이나 완료 상태가 바뀌었습니다. 최신 업무를 확인해 주세요.')
    until=datetime.combine(now.date()+timedelta(days=1),time(9),calendar.KST).isoformat() if body.action=='snooze' else None
    with calendar.db() as c:
        c.execute('INSERT INTO calendar_alert_states VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET state=excluded.state,until_at=excluded.until_at,updated_at=excluded.updated_at',
                  (body.key,body.action,until,now.isoformat()))
    return dict(saved=True)
