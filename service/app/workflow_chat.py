"""Bounded Korean workflow edits, resolved against saved stages, without LLM-written commands."""
import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import adhoc, adhoc_workflow as workflow

POLITE = r'\s*(?:줘|주세요|주실래요|줄래요|줄래)?'
ADD = r'(?:추가(?:해|하여|시켜)?|넣어|만들어)' + POLITE
MOVE = r'(?:옮겨|이동(?:해|시켜)?|배치해)' + POLITE
CHANGE = r'(?:바꿔|수정해|변경해|고쳐)' + POLITE
WRITE = r'(?:적어|써)' + POLITE
REL = r'(?:다음|뒤|후|이후|전|앞|이전)(?:으로|로|에)?'
END = r'\s*[.!?。]*\s*$'
FIELDS = {'이름':'title','명칭':'title','제목':'title','설명':'detail','내용':'detail','할일':'detail',
          '주의점':'caution','주의사항':'caution','완료확인사항':'checks','완료조건':'checks','확인사항':'checks'}
ALIASES = {'intake': {'안내','안내확인','요청확인'}, 'request': {'모집','희망자모집','요청','모집안내'},
           'collect': {'취합','수합','회신','회신취합','회신수집'},
           'review': {'검토','검수','중복검토','누락검토','누락중복검토'},
           'report': {'결과보고','보고','명단결과보고','마무리'}}
EXAMPLES = '예: 검토 다음에 부서장 확인 단계를 넣어줘 / 부서장 확인을 검토 앞으로 옮겨줘 / 부서장 확인 이름을 최종 확인으로 바꿔줘'


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')
    education_job_id: str | None = Field(default=None, pattern='^[0-9a-f]{32}$')
    workflow_revision: int | None = Field(default=None, ge=0, strict=True)
    workflow_data_version: int | None = Field(default=None, ge=1, strict=True)
    workflow_request_id: uuid.UUID | None = None
    workflow_selection: dict[str, str] = Field(default_factory=dict, max_length=3)

    @model_validator(mode='after')
    def valid(self):
        if (self.workflow_revision is None) != (self.workflow_data_version is None):
            raise ValueError('진행표 버전과 명단 버전을 함께 보내 주세요.')
        if not self.education_job_id and (self.workflow_revision is not None or self.workflow_selection):
            raise ValueError('단계와 버전을 확인할 교육 취합 업무를 함께 보내 주세요.')
        if any(k not in ('anchor','target','existing') or not re.fullmatch(r'[a-z0-9_-]{1,50}', v)
               for k, v in self.workflow_selection.items()):
            raise ValueError('선택한 단계를 다시 확인해 주세요.')
        return self


@dataclass(frozen=True)
class Operation:
    action: str
    target: str = ''
    title: str = ''
    anchor: str = ''
    relation: str = ''
    field: str = ''
    value: str = ''
    position: int | None = None


@dataclass(frozen=True)
class _EditRequest:
    query: str
    args: Input
    request_id: str
    digest: str

    def reply(self, status, summary, answer='', **payload):
        return response(self.query, self.request_id, status, summary, answer, **payload)


def normalized(text):
    return re.sub(r'[\s·ㆍ・.\-\'"“”‘’`]', '', unicodedata.normalize('NFKC', text)).casefold()


def name(text):
    text = text.strip()
    text = re.sub(r'\s*단계(?:를|을|의)?\s*$', '', text)
    text = text.strip().strip('"\'“”‘’`').strip()
    return text


def strip_object(text):
    text = re.sub(r'(?:를|을)\s*$', '', text.strip())
    return name(text)


QUOTED = r'"([^"\n]*)"|\'([^\'\n]*)\'|“([^”\n]*)”|‘([^’\n]*)’'


def parse(query, steps=()):
    # Protect literal values and whole saved titles before interpreting words such as '후' or '내용'.
    tokens = {}
    def token(value):
        key = 'ZZWORKFLOW' + uuid.uuid4().hex + 'ZZ'
        tokens[key] = value
        return key
    query = re.sub(r'^\s*(?:(?:이\s*업무(?:의)?\s*)?(?:교육\s*취합\s*)?진행표(?:에서|에|의)?\s*[,：:]?\s*)', '', query.strip())
    titles = sorted({s['title'] for s in steps}, key=len, reverse=True)
    pattern = QUOTED
    if titles:
        follows = r'(?=\s*(?:를|을|의|(?:단계(?:를|을|의)?\s*)?(?:완료\s*확인사항|완료\s*조건|확인사항|주의사항|주의점|이름|명칭|제목|설명|내용|할\s*일)|(?:바로\s*)?' + REL + r'(?:\s|$)))'
        pattern += '|(?:' + '|'.join(re.escape(t).replace(r'\ ', r'\s*') for t in titles) + ')' + follows
    def protect(match):
        quoted = next((v for v in match.groups() if v is not None), None)
        if quoted is not None:
            return '"' + token(quoted) + '"'
        prefix = query[:match.start()]
        is_target = not prefix.strip()
        is_move_anchor = re.search(MOVE + END, query) and re.search(r'(?:를|을)\s*$', prefix)
        return token(match[0]) if is_target or is_move_anchor else match[0]
    # A single pass never searches generated tokens for another saved title (including numeric titles).
    text = re.sub(pattern, protect, query)
    op = _parse(text)
    if op is None:
        return None
    def restore(value):
        if not isinstance(value, str):
            return value
        return re.sub(r'ZZWORKFLOW[0-9a-f]{32}ZZ', lambda m: tokens.get(m[0], m[0]), value)
    return Operation(**{key: restore(value) for key, value in vars(op).items()})


def _parse(query):
    text = re.sub(r'^\s*(?:(?:이\s*업무(?:의)?\s*)?(?:교육\s*취합\s*)?진행표(?:에서|에|의)?\s*[,：:]?\s*)', '', query.strip())
    outside_quotes = re.sub(r'(["\'“‘]).*?["\'”’]', '', text, flags=re.S)
    if re.search(r'넣고|추가하고|바꾸고|수정하고|옮기고|이동하고', outside_quotes):
        return None
    if len(re.findall(r'추가(?:해|하여|시켜)|넣어|만들어|옮겨|이동(?:해|시켜)|배치해|바꿔|수정해|변경해|고쳐|적어|써', outside_quotes)) > 1:
        return None
    flags = re.S
    field = r'(?P<field>완료\s*확인사항|완료\s*조건|확인사항|주의사항|주의점|이름|명칭|제목|설명|내용|할\s*일)'
    prefix = r'^(?P<target>.+?)\s*(?:단계)?\s*(?:의\s*)?' + field + r'(?:을|를)?\s*'
    for tail in (r'(?P<value>.+?)(?:으로|로)\s*' + CHANGE, r'(?P<value>.+?)\s*' + WRITE):
        match = re.match(prefix + tail + END, text, flags)
        if match:
            f = FIELDS[re.sub(r'\s+', '', match['field'])]
            return Operation('edit', target=name(match['target']), field=f, value=name(match['value']) if f=='title' else match['value'].strip().strip('"\'“”‘’`'))
    match = re.match(r'^(?P<target>.+?)(?:를|을)\s*(?P<value>.+?)(?:으로|로)\s*' + CHANGE + END, text, flags)
    if match:
        return Operation('edit',target=name(match['target']),field='title',value=name(match['value']))
    match = re.match(r'^(?P<target>.+?)(?:를|을)\s*(?:맨\s*)?(?P<place>처음|마지막|앞|뒤)(?:으로|로|에)?\s*' + MOVE + END, text, flags)
    if match:
        return Operation('move',target=name(match['target']),relation='first' if match['place'] in ('처음','앞') else 'last')
    match = re.match(r'^(?P<target>.+?)(?:를|을)\s*(?P<position>\d+)\s*(?:번째|번)(?:으로|로|에)\s*' + MOVE + END, text, flags)
    if match:
        return Operation('move',target=name(match['target']),relation='position',position=int(match['position']))
    match = re.match(r'^(?P<target>.+?)(?:를|을)\s*(?P<anchor>.+?)\s*(?:바로\s*)?(?P<relation>' + REL + r')\s*' + MOVE + END, text, flags)
    if match:
        return Operation('move', target=name(match['target']), anchor=name(match['anchor']), relation='before' if any(w in match['relation'] for w in ('전','앞')) else 'after')
    match = re.match(r'^(?:맨\s*)?(?P<place>처음|마지막|앞|뒤)(?:에|으로|로)\s*(?P<title>.+?)\s*' + ADD + END, text, flags)
    if match:
        return Operation('add',title=strip_object(match['title']),relation='first' if match['place'] in ('처음','앞') else 'last')
    match = re.match(r'^(?P<anchor>.+?)\s*(?:바로\s*)?(?P<relation>' + REL + r')\s*(?P<title>.+?)\s*' + ADD + END, text, flags)
    if match:
        return Operation('add',title=strip_object(match['title']),anchor=name(match['anchor']),relation='before' if any(w in match['relation'] for w in ('전','앞')) else 'after')
    match = re.match(r'^(?P<title>.+?)\s*' + ADD + END, text, flags)
    if match:
        return Operation('add',title=strip_object(match['title']))
    return None


def is_request(query, selected=False):
    # Quoted instructions inside an ordinary question never become a command.
    intent = re.sub(QUOTED, '', query)
    if re.search(r'어떻게|무슨\s*뜻|무슨\s*말|맞나요|맞는지|법적|근거\s*(?:규정|법령)', intent):
        return False
    imperative = re.search('(?:' + ADD + '|' + MOVE + '|' + CHANGE + '|' + WRITE + r'|삭제해' + POLITE + r'|완료해' + POLITE + ')' + END, query, re.S)
    if not imperative:
        return False
    if re.search(r'단계|진행표', query):
        return True
    op = parse(query)
    # A selected workflow must not turn a request to draft a document or create a new job into an added stage.
    if op is None or op.action == 'add' and not op.relation:
        return False
    return bool(selected or re.search(r'검토|모집|취합|부서장|명단|보고', query))


def compact(steps):
    return [dict(id=s['id'],title=s['title'],status=s['status']) for s in steps]


def job_info(v):
    return dict(id=v['id'],title=v['settings']['title'],revision=v['workflow']['revision'],data_version=v['version'])


def response(query, request_id, status, summary, answer='', **payload):
    return dict(query=query, mode='workflow_edit', model=None, profile=None, summary=summary, answer=answer,
                notice='', plan=None, alternatives=[], cited=[], related=[], personal_notes=[],
                workflow_chat=dict(status=status,request_id=request_id,selection={},before=[],after=[],changes=[]) | payload)


def candidates(c):
    out=[]
    for row in c.execute('SELECT j.id,j.settings,j.version,COALESCE(w.revision,0) AS revision FROM jobs j LEFT JOIN job_workflows w ON w.job_id=j.id ORDER BY j.created_at DESC,j.id'):
        settings=json.loads(row['settings'])
        if adhoc.layout(settings)['kind']=='education':
            out.append(dict(id=row['id'],title=settings['title'],course=settings['course'],event_date=settings['event_date'],
                            revision=row['revision'],data_version=row['version']))
    return out


def matches(phrase, steps):
    literal=normalized(phrase.strip().strip('"\'“”‘’`'))
    exact=[s for s in steps if normalized(s['title'])==literal]
    if exact:
        ids={s['id'] for s in exact} | {s['id'] for s in steps if literal in ALIASES.get(s['kind'],set())}
        return [s for s in steps if s['id'] in ids]
    ordinal=re.fullmatch(r'(?:제\s*)?(\d+)\s*(?:번째|번|단계)?', phrase)
    if ordinal:
        n=int(ordinal[1]);return steps[n-1:n] if 1<=n<=len(steps) else []
    key=normalized(name(phrase))
    if not key:return []
    exact=[s for s in steps if normalized(s['title'])==key]
    alias=[s for s in steps if key in ALIASES.get(s['kind'],set())]
    if exact:
        ids={s['id'] for s in exact+alias}
        return [s for s in steps if s['id'] in ids]
    return [s for s in steps if s in alias or key in normalized(s['title'])]


class NeedChoice(Exception):
    def __init__(self,role,phrase,options):
        self.role,self.phrase,self.options=role,phrase,options


def resolve(phrase, role, steps, selection):
    choices=matches(phrase,steps)
    chosen=selection.get(role)
    if chosen:
        match=next((s for s in choices if s['id']==chosen),None)
        if not match:raise ValueError('선택한 단계가 요청과 맞지 않아요. 최신 진행표에서 다시 골라 주세요.')
        return match
    if len(choices)!=1:raise NeedChoice(role,phrase,choices)
    return choices[0]


def command_for(op, steps, selection):
    target=None
    if op.action in ('edit','move'):
        target=resolve(op.target,'target',steps,selection)
    elif op.action=='add':
        if not op.title or len(op.title)>100:raise ValueError('추가할 단계 이름을 1~100자로 알려주세요.')
        exact=[s for s in steps if normalized(s['title'])==normalized(op.title)]
        if exact:
            target=resolve(op.title,'existing',exact,selection)
    if op.action=='edit':
        value=op.value.strip()
        if not value:raise ValueError('바꿀 내용을 알려주세요.')
        if op.field=='title' and any(s['id']!=target['id'] and normalized(s['title'])==normalized(value) for s in steps):
            raise ValueError('같은 이름의 단계가 있어요. 구분할 수 있는 다른 이름을 알려주세요.')
        data={op.field:[v.strip() for v in re.split(r'[\n;]',value) if v.strip()] if op.field=='checks' else value}
        return dict(action='edit',step_id=target['id'],**data)
    if op.action=='add' and target and not op.relation:
        return None
    rest=[s for s in steps if not target or s['id']!=target['id']]
    before=None
    if op.relation in ('before','after'):
        anchor=resolve(op.anchor,'anchor',steps,selection)
        if target and target['id']==anchor['id']:raise ValueError('같은 단계를 자기 앞이나 뒤로 옮길 수 없어요.')
        index=next(i for i,s in enumerate(rest) if s['id']==anchor['id'])+(op.relation=='after')
        before=rest[index]['id'] if index<len(rest) else None
    elif op.relation=='first':before=rest[0]['id'] if rest else None
    elif op.relation=='position':
        if not 1<=op.position<=len(rest)+1:raise ValueError('현재 단계 수 안에서 이동할 번호를 알려주세요.')
        before=rest[op.position-1]['id'] if op.position<=len(rest) else None
    if target:
        return dict(action='move',step_id=target['id'],before_id=before)
    result=dict(action='add',title=op.title)
    if before is not None:result['before_id']=before
    return result


def _replayed_response(c, request: _EditRequest):
    receipt=c.execute('SELECT * FROM workflow_chat_requests WHERE request_id=?',(request.request_id,)).fetchone()
    if not receipt:
        return None
    if receipt['query_hash']!=request.digest or request.args.education_job_id and request.args.education_job_id!=receipt['job_id']:
        return request.reply('conflict','다른 요청에 사용한 번호예요. 새 메시지로 다시 요청해 주세요.')
    saved=json.loads(receipt['response']);saved['workflow_chat']['replayed']=True
    return saved


def _selected_job(c, request: _EditRequest):
    jobs=candidates(c)
    selected=next((j for j in jobs if j['id']==request.args.education_job_id),None) if request.args.education_job_id else jobs[0] if len(jobs)==1 else None
    if selected is None:
        if request.args.education_job_id:
            return None,request.reply('needs_detail','선택한 교육 취합 업무를 찾지 못했어요. 다른 업무를 선택해 주세요.')
        return None,request.reply('choose_job','어느 교육 취합 업무를 수정할까요?' if jobs else '먼저 교육 희망자 취합 업무를 만들어 주세요.',
                                  '선택한 업무의 진행표에만 반영해요.',candidates=jobs[:30])
    return adhoc.view(c,selected['id']),None


def _edit_selected_job(c, request: _EditRequest, v):
    info=job_info(v)
    if request.args.workflow_revision is not None and (request.args.workflow_revision!=info['revision'] or request.args.workflow_data_version!=info['data_version']):
        return request.reply('conflict','진행표나 명단이 바뀌었어요. 최신 내용을 확인한 뒤 다시 요청해 주세요.',job=info)
    op=parse(request.query,v['workflow']['steps'])
    if op is None:
        return request.reply('unsupported','한 번에 한 단계의 추가·수정·이동을 요청해 주세요.',EXAMPLES,job=info)
    selection=dict(request.args.workflow_selection)
    try:
        command=command_for(op,v['workflow']['steps'],selection)
    except NeedChoice as need:
        if not need.options:
            return request.reply('needs_detail',f'“{need.phrase}” 단계를 찾지 못했어요.',
                                 '현재 단계: '+' → '.join(s['title'] for s in v['workflow']['steps'])+'\n'+EXAMPLES,job=info)
        choices=[dict(id=s['id'],title=s['title'],position=next(i for i,t in enumerate(v['workflow']['steps'],1) if t['id']==s['id'])) for s in need.options]
        result=request.reply('choose_step',f'“{need.phrase}”에 맞는 단계가 여러 개예요. 어느 단계인가요?',job=info,role=need.role,choices=choices)
        result['workflow_chat']['selection']=selection
        return result
    except ValueError as exc:
        return request.reply('needs_detail',str(exc),EXAMPLES,job=info)
    return _apply_and_record(c,request,v,op,command)


def _apply_and_record(c, request: _EditRequest, v, op, command):
    info=job_info(v);before=compact(v['workflow']['steps'])
    try:
        if command is not None:
            workflow.update(c,v,workflow.Command(revision=info['revision'],data_version=info['data_version'],**command))
    except (HTTPException,ValidationError) as exc:
        # No workflow update commits before validation; the surrounding transaction rolls back on unexpected failures.
        if isinstance(exc,HTTPException):message=exc.detail
        else:message='단계 이름은 100자, 설명은 2000자, 주의점은 1500자 안에서 알려주세요. 확인사항은 항목별 300자까지예요.'
        return request.reply('needs_detail',message,job=info)
    after_v=adhoc.view(c,v['id']);after=compact(after_v['workflow']['steps']);after_info=job_info(after_v)
    changed=after_info['revision']!=info['revision']
    changes=[]
    target_id=command.get('step_id') if command else None
    old=next((s for s in v['workflow']['steps'] if s['id']==target_id),None)
    new=next((s for s in after_v['workflow']['steps'] if s['id']==target_id),None)
    for key,label in [('title','단계 이름'),('detail','설명'),('caution','주의점'),('checks','완료 확인사항')]:
        if old and new and old[key]!=new[key]:
            changes.append(dict(field=label,before='\n'.join(old[key]) if isinstance(old[key],list) else old[key],after='\n'.join(new[key]) if isinstance(new[key],list) else new[key]))
    if changed:
        row=c.execute('SELECT id,detail FROM job_workflow_history WHERE job_id=? AND revision=?',(v['id'],after_info['revision'])).fetchone()
        audit=json.loads(row['detail']);audit.update(source='chat',request_id=request.request_id,request_text=request.query)
        c.execute('UPDATE job_workflow_history SET detail=? WHERE id=?',(workflow.encode(audit),row['id']))
    summary='진행표를 수정했어요.' if changed else '이미 요청한 상태예요. 단계를 중복해서 만들지 않았어요.'
    if changed and op.action=='add' and command['action']=='move':summary='같은 이름의 단계가 있어 기존 단계를 요청한 위치로 옮겼어요.'
    result=request.reply('applied' if changed else 'unchanged',summary,
                         '내용을 바꾼 완료 단계는 다시 확인하도록 표시했어요.' if changed and command['action']=='edit' and old['completed_at'] else '',
                         job=after_info,before=before,after=after,changes=changes)
    c.execute('INSERT INTO workflow_chat_requests VALUES(?,?,?,?,?)',(request.request_id,v['id'],request.digest,workflow.encode(result),workflow.stamp()))
    return result


def handle(query, body):
    if body.get('card_id') or body.get('leave_type') or not is_request(query, bool(body.get('education_job_id'))):
        return None
    try:
        args=Input(**{k:body[k] for k in Input.model_fields if k in body})
    except ValidationError as exc:
        raise HTTPException(422,'대화의 업무·버전 정보를 다시 확인해 주세요.') from exc
    request_id=str(args.workflow_request_id or uuid.uuid4())
    op=parse(query)
    if op is None:
        return response(query,request_id,'unsupported','한 번에 한 단계의 추가·수정·이동을 요청해 주세요.',EXAMPLES+'\n단계 완료와 삭제는 진행표 화면에서 확인할 수 있어요.')
    digest=hashlib.sha256(query.encode()).hexdigest()
    request=_EditRequest(query,args,request_id,digest)
    with adhoc.db() as c:
        c.execute('BEGIN IMMEDIATE')
        replay=_replayed_response(c,request)
        if replay is not None:
            return replay
        v,error=_selected_job(c,request)
        if error is not None:
            return error
        return _edit_selected_job(c,request,v)
