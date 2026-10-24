"""Education calendar projections and a work panel over existing collection APIs."""
from datetime import date, timedelta
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Query
from . import adhoc, adhoc_workflow, adhoc_workspace, toolbox

router = APIRouter(prefix='/api/calendar/education', tags=['교육 단계 달력'])


def workflow_href(key, step):
    return f'adhoc.html?step={quote(step, safe="")}#job-{quote(key, safe="")}'


def education_view(c, key):
    value = adhoc.view(c, key)
    if value['workflow'] is None:
        raise HTTPException(422, '교육 취합 업무의 진행표에서 사용할 수 있어요.')
    return value


def stage_events(value):
    """Only assigned dates; never infer dates for the remaining stages."""
    workflow = value['workflow']
    for step in workflow['steps']:
        if not step['due_date']:
            continue
        due = step['due_date']
        status = ('지연 · ' if step['overdue'] else '') + step['status_label']
        tag = 'deadline' if step['kind'] == 'collect' else 'step:' + step['id']
        yield dict(tag=tag, title=f"{value['settings']['title']} · {step['title']} · {status}",
                   start=due, end=(date.fromisoformat(due) + timedelta(days=1)).isoformat(),
                   properties=dict(education_job=True, education_step_id=step['id'],
                     step_status=step['status'], step_status_label=step['status_label'],
                     overdue=step['overdue'], due_source=step['due_source'],
                     data_version=value['version'], workflow_revision=workflow['revision'],
                     work_href=workflow_href(value['id'], step['id'])))


@router.get('/{key}')
def snapshot(key: str, step_id: str | None = Query(default=None, max_length=50)):
    with adhoc.db() as c:
        v = education_view(c, key)
        w = v['workflow'];steps = w['steps']
        if step_id and not any(s['id'] == step_id for s in steps):
            raise HTTPException(404, '해당 단계가 삭제되었거나 바뀌었습니다. 업무를 다시 열어 주세요.')
        selected = step_id or w['next_step_id'] or steps[0]['id']
        files = [{k: f[k] for k in ('id', 'filename', 'department')} |
                 {'original_url': f"/api/adhoc/jobs/{quote(key, safe='')}/files/{quote(f['id'], safe='')}"}
                 for f in v['files']]
        attachments = toolbox.items(c, 'adhoc', key)
    base = f'/api/adhoc/jobs/{quote(key, safe="")}'
    template = v['settings'].get('template_snapshot') or {}
    return dict(job_id=key, title=v['settings']['title'], course=v['settings']['course'],
                event_date=v['settings']['event_date'], reply_deadline=v['settings']['deadline'],
                data_version=v['version'], revision=w['revision'], selected_step_id=selected,
                steps=steps, summary=v['summary'], departments=v['departments'], request_draft=v['request_draft'],
                workflow_url=workflow_href(key, selected), resources=dict(
                  template_url=base+'/template.xlsx', working_url=base+f"/working.xlsx?version={v['version']}",
                  registered_template_url=f"/api/adhoc/templates/{quote(template['id'], safe='')}/original" if template.get('id') else None,
                  files=files, attachments=attachments, folders=adhoc_workspace.related_folders(key)['linked'],
                  exports=[e | {'url': base+'/exports/'+quote(e['id'], safe='')} for e in v['exports']]))


@router.patch('/{key}/schedule')
def schedule(key: str, body: adhoc_workflow.Command):
    if body.action != 'schedule':
        raise HTTPException(422, '이 경로에서는 단계 마감만 변경할 수 있어요.')
    with adhoc.db() as c:
        c.execute('BEGIN IMMEDIATE')
        v = education_view(c, key)
        adhoc_workflow.update(c, v, body)
    return snapshot(key, body.step_id)
