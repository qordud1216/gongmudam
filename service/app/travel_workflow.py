"""업무함 상태는 실제 자료에서 계산하고 수동 메모 완료로 증빙 검증을 대체하지 않는다."""
from .travel_package import checklist

STAGES={'evidence':'증빙 등록','review':'거래·원본 확인','calculate':'규정 계산','recalculate':'재계산 필요',
        'needs_input':'계산 조건 보완','supplement':'보완 필요','draft':'초안 작성','handoff':'담당자 검토 준비'}


def draft_row(row,snapshot,current):
    calc=snapshot.get('calculation')
    fresh=bool(calc and not calc['stale'] and calc['result']['status']=='calculated_for_review')
    current_revision=current.get('workflow_revision',0)
    same=snapshot['version']==current['version'] and snapshot.get('workflow_revision',0)==current_revision
    return dict(id=row['id'],case_version=row['case_version'],workflow_revision=snapshot.get('workflow_revision',0),
                created_at=row['created_at'],is_current=same,
                estimated_total=calc['result']['estimated_total'] if fresh else None,
                calculation_status='미산정' if not calc else '재계산 필요' if calc['stale'] else calc['result']['status'],
                print_url=f'/api/travel/drafts/{row["id"]}/print',csv_url=f'/api/travel/drafts/{row["id"]}/csv',
                json_url=f'/api/travel/drafts/{row["id"]}',package_check_url=f'/api/travel/drafts/{row["id"]}/package-check')


def summarize(view,drafts):
    rows=view['review']['transactions'];calc=view.get('calculation');docs=view.get('documents',[])
    findings=checklist(view)
    required=[f for f in findings if f['level']=='required']
    unresolved=bool(view['parse_issues'] or any(t['decision']=='pending' or (t['included'] and t['flags']) for t in rows) or any(not d['confirmed_at'] for d in docs))
    if unresolved:stage='review'
    elif calc and calc['stale']:stage='recalculate'
    elif not calc:stage='calculate' if rows else 'evidence'
    elif calc['result']['status']!='calculated_for_review':stage='needs_input'
    elif required:stage='supplement'
    elif any(d['is_current'] for d in drafts):stage='handoff'
    else:stage='draft'
    fresh=bool(calc and not calc['stale'] and calc['result']['status']=='calculated_for_review')
    return dict(stage=stage,stage_label=STAGES[stage],required_count=len(required),
                pending_transactions=sum(t['decision']=='pending' for t in rows),
                unconfirmed_documents=sum(not d['confirmed_at'] for d in docs),
                open_tasks=sum(t['status']=='open' for t in view.get('tasks',[])),draft_count=len(drafts),
                latest_draft=drafts[0] if drafts else None,
                estimated_total=calc['result']['estimated_total'] if fresh else None,
                next_action={'evidence':'카드문자·영수증 원본을 등록하세요.','review':'보류 거래·원본·해석 실패 내역을 먼저 확인하세요.',
                             'calculate':'규정 계산 조건을 확인하고 산정하세요.','recalculate':'바뀐 거래·원본을 반영해 재계산하세요.',
                             'draft':'현재 상태로 새 초안을 만드세요.'}.get(stage,required[0]['message'] if required else '담당자가 준비 자료와 최종 지급·제출 조건을 확인해야 합니다.'))
