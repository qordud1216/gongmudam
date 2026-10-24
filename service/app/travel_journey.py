"""한 줄 업무 흐름의 읽기 전용 상태. 단계 열기는 승인·처리 완료가 아니다."""
from . import travel_package,travel_workflow

STEPS=[('trip','출장 확인'),('evidence','증빙 수집'),('review','거래 검토'),('calculate','여비 계산'),('draft','서식·초안'),('handoff','제출 준비')]


def build(view,drafts):
    summary=travel_workflow.summarize(view,drafts)
    rows=view['review']['transactions'];docs=view.get('documents',[]);calc=view.get('calculation')
    fresh=bool(calc and not calc['stale'] and calc['result']['status']=='calculated_for_review')
    pending=sum(t['decision']=='pending' for t in rows)
    flags=sum(bool(t['flags']) for t in rows if t['included'])
    unconfirmed=sum(not d['confirmed_at'] for d in docs)
    missing=sum(not t.get('document_ids') for t in rows if t['included'])
    parse=len(view['parse_issues']);current=[d for d in drafts if d['is_current']]
    findings=travel_package.checklist(view)
    required=[f for f in findings if f['level']=='required']
    states={}
    states['trip']=('recorded','등록됨','저장된 기관·일정·규정 사본입니다. 출장명령 진위와 기관 승인은 별도로 확인합니다.')
    if unconfirmed or missing:states['evidence']=('attention','원본 확인',f'미확인 원본 {unconfirmed}건 · 포함 거래 원본 미연결 {missing}건')
    elif rows or docs:states['evidence']=('recorded','자료 등록됨',f'거래 {len(rows)}건 · 원본 {len(docs)}건. 등록·대조 기록이며 공식 증빙 인증은 아닙니다.')
    else:states['evidence']=('waiting','자료 확인 필요','등록된 거래·원본이 없습니다. 미청구 항목·교육기관 비용 등 해당 증빙 요건도 확인하세요.')
    if pending or flags or parse:states['review']=('attention','검토 필요',f'보류 {pending}건 · 포함 거래 이상표시 {flags}건 · 해석 실패 {parse}건')
    elif rows:states['review']=('recorded','검토 기록 있음','거래별 포함·제외 기록입니다. 원본·규정·최종 지급 요건은 추가로 대조합니다.')
    else:states['review']=('waiting','거래 확인 필요','거래가 없거나 비용 미청구 조건입니다. 계산 유형과 증빙 범위를 함께 확인하세요.')
    if not view.get('legal_profile'):states['calculate']=('blocked','적용 기준 확인','이 출장에는 검증된 공식 계산 프로필이 없습니다. 다른 기관 기준을 자동 적용하지 않습니다.')
    elif calc and calc['stale']:states['calculate']=('attention','재계산 필요','출장·거래·원본 변경 전 계산입니다. 현재 입력으로 다시 계산하세요.')
    elif fresh and calc['result'].get('temporal',{}).get('is_estimate'):states['calculate']=('attention','예정 사전산정','여행 종료 후 실제 내역과 최신 규정으로 다시 계산해야 합니다.')
    elif fresh:states['calculate']=('recorded','검토용 산정됨','근거와 입력 사본으로 산정한 금액입니다. 최종 지급액 확정은 아닙니다.')
    elif calc:states['calculate']=('blocked','조건 보완', ' / '.join(b['message'] for b in calc['result'].get('blockers',[])) or '미지원 조건·필수 입력을 확인하세요.')
    else:states['calculate']=('waiting','미산정','지급구분·증빙·적용 조건을 확인한 뒤 계산하세요.')
    if current and fresh:states['draft']=('recorded','현재 초안 있음',f'현재 출장·보완 버전의 초안 {len(current)}건. 필수 검토 항목이 남아 있을 수 있습니다.')
    elif drafts:states['draft']=('attention','초안 재검토','현재 계산·출장·보완 버전과 저장한 초안을 대조하고 필요하면 새로 만드세요.')
    else:states['draft']=('waiting','초안 준비','기관 준비서식과 현재 검토 상태로 초안을 저장하세요.')
    if required:states['handoff']=('attention','보완 필요',f'현재 자료의 필수 확인 {len(required)}개. '+required[0]['message'])
    elif not current:states['handoff']=('waiting','현재 초안 필요','현재 버전의 초안을 만든 뒤 원본·묶음을 검사하세요.')
    else:states['handoff']=('waiting','담당자 검토 대기','목록상 필수 항목이 없습니다. 아래 묶음 검사로 저장 원본·해시를 확인한 뒤 담당자가 최종 검토합니다.')
    recommended={'evidence':'evidence','review':'review','calculate':'calculate','recalculate':'calculate','needs_input':'calculate','supplement':'handoff','draft':'draft','handoff':'handoff'}[summary['stage']]
    return dict(case_id=view['id'],case_version=view['version'],workflow_revision=view.get('workflow_revision',0),
        recommended_step=recommended,summary=summary,
        steps=[dict(id=key,title=title,status=states[key][0],label=states[key][1],reason=states[key][2]) for key,title in STEPS],
        checklist=findings,drafts=drafts,package_integrity_checked=False,
        notice='단계 선택·자료 등록·초안 저장은 기관 승인이나 지급 완료를 의미하지 않습니다.')
