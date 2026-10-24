"""Per-job education workflow. Its revision never changes the collection data version."""
import copy
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


SCHEMA = '''
CREATE TABLE IF NOT EXISTS job_workflows (
 job_id TEXT PRIMARY KEY REFERENCES jobs(id), revision INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS job_workflow_history (
 id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), revision INTEGER NOT NULL,
 action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
'''
DEPENDENT = {'collect', 'review', 'report', 'custom'}
STATUS = {'todo': '미완료', 'ready': '완료 가능', 'done': '완료', 'needs_review': '재확인 필요'}


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Reference(Strict):
    origin: Literal['knowledge', 'document', 'experience', 'template']
    id: str = Field(min_length=1, max_length=100)
    unit: int = Field(default=0, ge=0, le=100000)
    sha256: str = Field(pattern='^[0-9a-f]{64}$')


class Command(Strict):
    revision: int = Field(ge=0)
    data_version: int = Field(ge=1)
    action: Literal['add', 'edit', 'move', 'archive', 'restore', 'complete', 'reopen', 'schedule']
    step_id: str | None = Field(default=None, min_length=1, max_length=50)
    before_id: str | None = Field(default=None, min_length=1, max_length=50)
    title: str | None = Field(default=None, min_length=1, max_length=100)
    detail: str | None = Field(default=None, max_length=2000)
    caution: str | None = Field(default=None, max_length=1500)
    checks: list[str] | None = Field(default=None, max_length=20)
    references: list[Reference] | None = Field(default=None, max_length=12)
    due_date: date | None = None
    confirmed: bool = False


def stamp():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def step(key, title, detail, checks, caution):
    return dict(id=key, kind=key, title=title, detail=detail, checks=checks, caution=caution,
                references=[], archived=False, completed_at=None, completed_data_version=None,
                review_reason='')


def default():
    return dict(template_version=1, steps=[
        step('intake', '안내 확인', '교육 요청의 목적·대상·일정·회신 마감을 확인해요.',
             ['교육명·교육일·대상 부서·회신 마감을 확인했어요.'], '마감 시각·회신 경로·교육 정원은 요청 담당자에게 확인해요.'),
        step('request', '희망자 모집', '요청문과 같은 양식의 회신 서식을 준비해 부서에 안내해요.',
             ['요청문과 회신 서식을 확인하고 대상 부서에 전달했어요.'], '요청문 복사는 실제 발송이 아니에요. 전달 여부는 담당자가 확인해요.'),
        step('collect', '회신 취합', '부서별 회신 파일을 모으고, 희망자가 없는 부서도 따로 기록해요.',
             ['모든 부서의 회신 또는 희망자 없음 기록을 확인했어요.'], '희망자 없음과 미회신은 구분해요.'),
        step('review', '누락·중복 검토', '누락·불일치·중복 의심을 원본과 대조하고 포함·제외 사유를 남겨요.',
             ['오류와 중복 의심을 대조하고 포함·제외 처리를 확인했어요.'], '중복 의심만으로 임의 삭제하지 않아요. 이름이 같아도 다른 사람일 수 있어요.'),
        step('report', '명단·결과보고', '현재 버전의 취합본을 저장하고 명단·부서별 집계·출처를 확인해요.',
             ['현재 버전의 취합본을 열어 결과를 확인했어요.'], '참석 희망자 취합본이에요. 대상자 확정·실제 보고·제출은 담당자가 별도로 처리해요.'),
    ])


def load(c, key):
    row = c.execute('SELECT revision,payload FROM job_workflows WHERE job_id=?', (key,)).fetchone()
    return (row['revision'], json.loads(row['payload'])) if row else (0, default())


def ref_key(ref):
    return ref['origin'], ref['id'], ref.get('unit', 0)


def catalog(c):
    """Only registered resources; do not accept arbitrary paths or client-written quotations."""
    from . import knowledge, store, folders, official_sources
    result = []
    for source in knowledge.sources():
        if not source['enabled'] or not source['current']:
            continue
        official = official_sources.metadata(source['sha256'])
        for i, unit in enumerate(source['units']):
            result.append(dict(origin='knowledge', id=source['id'], unit=i,
                               title=source['title'], kind=source['kind'], sha256=source['sha256'],
                               loc=unit.get('loc', ''), text=unit['text'],
                               href='folders.html#' + source['library_id'],
                               source_url=official['source_url'] if official else '',
                               official=bool(official), effective_date=source.get('effective_date', '')))
    documents = {}
    for doc in store.list_documents():
        try:
            path = store.document_path(doc)
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != doc['sha256']:
                continue
        except OSError:
            continue
        documents[doc['id']] = doc
    for chunk in store.all_chunks():
        doc = documents.get(chunk['doc_id'])
        if not doc:
            continue
        result.append(dict(origin='document', id=chunk['id'], unit=0, title=doc['title'],
                           kind=doc['kind'], sha256=doc['sha256'], loc=chunk.get('loc', ''), text=chunk['text'],
                           href='/api/documents/' + doc['id'] + '/download', source_url='', official=False,
                           note=doc.get('note', '')))
    with folders.db() as notes:
        records = notes.execute('SELECT payload FROM work_experiences').fetchall()
    for row in records:
        note = json.loads(row['payload'])
        content = f"상황: {note['situation']}\n처리: {note['handling']}\n주의점: {note['caution']}"
        result.append(dict(origin='experience', id=note['id'], unit=0, title=note['title'],
                           kind='담당자 경험 · 공식 근거 아님', sha256=hashlib.sha256(content.encode()).hexdigest(),
                           loc=note.get('project_name', ''), text=content, href='folders.html#' + note['library_id'],
                           source_url='', official=False))
    for row in c.execute('SELECT id,institution,name,version_label,config,sha256 FROM collection_templates'):
        config = json.loads(row['config'])
        result.append(dict(origin='template', id=row['id'], unit=0,
                           title=f"{row['institution']} / {row['name']} / {row['version_label']}", kind='기관 취합 서식',
                           sha256=row['sha256'], loc=config['sheet_name'], text=' / '.join(config['headers']),
                           href='/api/adhoc/templates/' + row['id'] + '/original', source_url='', official=False))
    return result


def reference_options(c, query=''):
    query = query.strip().casefold()
    choices = catalog(c)
    return [r for r in choices if not query or query in (r['title'] + ' ' + r['text']).casefold()][:150]


def rules_for(s, v):
    automatic = []
    if s['kind'] == 'collect':
        automatic = [dict(text='모든 대상 부서 회신 확인',
                          ok=v['summary']['missing'] == 0),
                     dict(text='회신과 희망자 없음 기록의 충돌 해소', ok=not any(d['conflict'] for d in v['departments']))]
    elif s['kind'] == 'review':
        automatic = [dict(text='미회신·보류 행·회신 충돌 점검 통과', ok=v['can_finalize'])]
    elif s['kind'] == 'report':
        automatic = [dict(text='현재 명단 버전의 취합본 저장', ok=any(e['is_current'] for e in v['exports']))]
    return automatic


def project(c, v):
    if v['layout']['kind'] != 'education':
        return None
    revision, payload = load(c, v['id'])
    refs = [r for s in payload['steps'] if not s['archived'] for r in s['references']]
    current_refs = {ref_key(r): r for r in catalog(c)} if refs else {}
    active, archived = [], []
    for original in payload['steps']:
        s = copy.deepcopy(original)
        if s['archived']:
            archived.append(s)
            continue
        checks = rules_for(s, v)
        reasons = [check['text'] for check in checks if not check['ok']]
        for ref in s['references']:
            current = current_refs.get(ref_key(ref))
            ref['current'] = bool(current and current['sha256'] == ref['sha256'] and current['text'] == ref['text'])
            if not ref['current']:
                reasons.append('연결 자료 변경·삭제 확인: ' + ref['title'])
        stale = s['review_reason']
        if s['completed_at'] and s['kind'] in DEPENDENT and s['completed_data_version'] != v['version']:
            stale = '명단 자료가 바뀌었어요. 이 단계를 다시 확인해 주세요.'
        if s['completed_at'] and reasons:
            stale = stale or '완료 조건이나 연결 자료를 다시 확인해 주세요.'
        status = 'needs_review' if s['completed_at'] and stale else 'done' if s['completed_at'] else 'ready' if not reasons else 'todo'
        due = v['settings'].get('deadline') if s['kind'] == 'collect' else s.get('due_date')
        today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
        s.update(due_date=due, due_source='reply_deadline' if s['kind'] == 'collect' else 'step_plan' if due else 'unset',
                 overdue=bool(due and due < today and status != 'done'),
                 status=status, status_label=STATUS[status], can_complete=not reasons,
                 blockers=reasons, automatic_checks=checks, review_reason=stale)
        active.append(s)
    history = [dict(r) | {'detail': json.loads(r['detail'])} for r in c.execute(
        'SELECT revision,action,detail,created_at FROM job_workflow_history WHERE job_id=? ORDER BY id DESC LIMIT 60', (v['id'],))]
    return dict(revision=revision, data_version=v['version'], template_version=payload['template_version'],
                steps=active, archived=archived, next_step_id=next((s['id'] for s in active if s['status'] != 'done'), None),
                completed_count=sum(s['status'] == 'done' for s in active), history=history)


def update(c, v, command):
    if v['layout']['kind'] != 'education':
        raise HTTPException(422, '교육 참석 희망자 취합 업무에서 진행표를 사용할 수 있어요.')
    revision, payload = load(c, v['id'])
    if revision != command.revision or v['version'] != command.data_version:
        raise HTTPException(409, '명단 또는 진행표가 바뀌었습니다. 최신 내용을 다시 열어 주세요.')
    before = copy.deepcopy(payload)
    schedule_change = None
    entries = payload['steps']
    target = next((s for s in entries if s['id'] == command.step_id), None)
    if command.action != 'add' and (not target or target['archived'] and command.action != 'restore'):
        raise HTTPException(404, '진행표 단계를 찾을 수 없습니다.')
    if command.checks is not None:
        if any(not text.strip() or len(text) > 300 for text in command.checks):
            raise HTTPException(422, '완료 확인사항은 항목별 1~300자로 입력하세요.')
    if command.action == 'add':
        if sum(not s['archived'] for s in entries) >= 30 or len(entries) >= 100:
            raise HTTPException(422, '이 업무에는 활성 단계 30개, 삭제 기록 포함 100개까지 둘 수 있어요.')
        if not command.title:
            raise HTTPException(422, '추가할 단계의 이름을 입력하세요.')
        target = step(uuid.uuid4().hex, command.title, command.detail or '', command.checks or [], command.caution or '')
        target['kind'] = 'custom'
        entries.append(target)
    if command.action in ('add', 'edit'):
        for name in ('title', 'detail', 'caution', 'checks'):
            value = getattr(command, name)
            if value is not None:
                target[name] = value
        if command.references is not None:
            options = {ref_key(r): r for r in catalog(c)}
            selected = []
            for ref in command.references:
                key = (ref.origin, ref.id, ref.unit)
                if key not in options or options[key]['sha256'] != ref.sha256:
                    raise HTTPException(422, '등록 자료가 바뀌었거나 사용할 수 없어요. 자료를 다시 선택하세요.')
                if not any(ref_key(r) == key for r in selected):
                    selected.append(options[key])
            target['references'] = selected
        if command.action == 'edit' and target != next(s for s in before['steps'] if s['id'] == target['id']) and target['completed_at']:
            target['review_reason'] = '단계 내용이나 연결 자료를 수정했어요. 다시 확인해 주세요.'
    if command.action in ('move', 'add') and (command.action == 'move' or command.before_id is not None):
        if command.before_id == target['id']:
            raise HTTPException(422, '같은 단계 앞으로 이동할 수 없어요.')
        destination = next((s for s in entries if s['id'] == command.before_id and not s['archived']), None)
        if command.before_id and destination is None:
            raise HTTPException(422, '이동할 위치의 단계를 다시 선택하세요.')
        entries.remove(target)
        entries.insert(entries.index(destination) if destination else len(entries), target)
    if command.action == 'archive':
        if target['kind'] != 'custom':
            raise HTTPException(422, '기본 5단계는 유지해요. 설명이나 순서는 수정할 수 있어요.')
        target['archived'] = True
    if command.action == 'restore':
        if not target['archived']:
            raise HTTPException(422, '삭제한 추가 단계만 복원할 수 있어요.')
        if sum(not s['archived'] for s in entries) >= 30:
            raise HTTPException(422, '활성 단계는 30개까지 둘 수 있어요.')
        target['archived'] = False
        if target['completed_at']:
            target['review_reason'] = '복원한 단계를 다시 확인해 주세요.'
    if command.action == 'complete':
        projected = next(s for s in project(c, v)['steps'] if s['id'] == target['id'])
        if not command.confirmed:
            raise HTTPException(422, '담당자가 완료 확인사항을 확인해 주세요.')
        if not projected['can_complete']:
            raise HTTPException(422, '먼저 확인할 내용: ' + ' · '.join(projected['blockers']))
        if projected['status'] == 'done':
            return
        target.update(completed_at=stamp(), completed_data_version=v['version'], review_reason='')
    if command.action == 'reopen':
        target.update(completed_at=None, completed_data_version=None, review_reason='')
    if command.action == 'schedule':
        if 'due_date' not in command.model_fields_set:
            raise HTTPException(422, '마감일을 지정하거나 비워 주세요.')
        due = command.due_date.isoformat() if command.due_date else None
        if command.due_date and not 2000 <= command.due_date.year <= 2100:
            raise HTTPException(422, '마감일은 2000~2100년 범위에서 지정하세요.')
        original = v['settings'].get('deadline') if target['kind'] == 'collect' else target.get('due_date')
        if due == original:
            return
        if target['kind'] == 'collect':
            if not due or due > v['settings']['event_date']:
                raise HTTPException(422, '회신 마감일은 교육일까지의 날짜로 지정하세요.')
            if not command.confirmed:
                raise HTTPException(422, '원본 회신 마감 변경과 기존 취합본 재검토 영향을 확인해 주세요.')
            from . import adhoc
            settings = copy.deepcopy(v['settings']);settings['deadline'] = due
            adhoc.bump(c, v['id'], v['version'])
            c.execute('UPDATE jobs SET settings=? WHERE id=?', (encode(settings), v['id']))
            adhoc.log(c, v['id'], '회신 마감 변경', dict(before=original, after=due, previous_version=v['version']))
            for entry in entries:
                if entry['completed_at']:
                    entry['review_reason'] = '회신 마감일이 바뀌었어요. 완료 내용을 다시 확인해 주세요.'
        else:
            target['due_date'] = due
            if target['completed_at']:
                target['review_reason'] = '단계 계획 마감일이 바뀌었어요. 다시 확인해 주세요.'
        schedule_change = dict(before=original, after=due, source_changed=target['kind'] == 'collect')
    if payload == before and schedule_change is None:
        return
    revision += 1
    c.execute('INSERT INTO job_workflows VALUES(?,?,?) ON CONFLICT(job_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload',
              (v['id'], revision, encode(payload)))
    c.execute('INSERT INTO job_workflow_history(job_id,revision,action,detail,created_at) VALUES(?,?,?,?,?)',
              (v['id'], revision, command.action, encode(dict(step_id=target['id'], before=before, after=payload,
               **({'schedule': schedule_change} if schedule_change else {}))), stamp()))
