"""Deterministic preparation guidance; source interpretation stays in reviewed trees.

The data map records provenance, not inferred legal applicability. A generated
graph (including Graphify output) is never accepted as an authoritative rule.
"""
import re
from . import knowledge, manual_knowledge, answer_tree, task_intent, store

TOPICS = (
    ('goods', '물품 구매·검수', r'물품|사무용품|구매|검수|예산\s*목|예산\s*과목'),
    ('education', '교육 희망자 취합', r'교육.*(?:취합|희망자|모집)|희망자.*취합'),
    ('folder', '업무자료 정리', r'폴더|자료함|파일\s*정리'),
    ('leave', '휴가·복무', r'휴가|연가|공가|병가|대체휴무|특가|근무상황'),
    ('overtime', '초과근무', r'초과근무|시간외근무'),
    ('flex', '근무형태', r'유연근무|시차출퇴근'),
    ('duty', '당직', r'당직'),
    ('security', '보안점검', r'보안점검'),
    ('travel', '출장·여비', r'출장|여비'),
)
PREPARATION = {
    'travel': [('scope','적용 조건 확인','소속 기관과 실제 출장 일정, 이동수단·숙박·제공받은 항목을 확인해요.'),
               ('materials','증빙·서식 준비','아래 등록 근거에서 필요한 증빙과 기한을 확인하고, 기관에서 쓰는 서식을 준비해요.'),
               ('system','e-사람에서 신청·정산','아래 매뉴얼의 원문과 쪽수를 참고해 기관 시스템에서 처리해요. 화면·권한 차이는 담당자에게 확인해요.'),
               ('check','처리 결과 확인','신청·결재 상태와 보완 요청을 확인해요. 필요하면 아래 보조 도구에서 계산·증빙을 검토할 수 있어요.')],
    'leave': [('scope','휴가 종류·적용 대상 확인','휴가 사유와 근무 형태, 소속 기관에 맞는 기준을 확인해요.'),
              ('materials','기간·서류 확인','아래 규정에서 기간과 필요한 증빙을 확인하고 기관 양식을 준비해요.'),
              ('system','e-사람에서 신청','해당 종류의 신청 화면을 아래 매뉴얼에서 확인하고 기관 시스템에서 처리해요.'),
              ('check','승인·반영 확인','승인 여부와 근무상황 반영을 확인해요.')],
    'goods': [('scope','품목·예산·계약 조건 확인','품목, 기관·회계 구분과 적용 연도를 먼저 확인해요.'),
              ('materials','필요 자료 준비','아래 근거와 기관 양식에서 구매·계약·검수에 필요한 자료를 확인해요.'),
              ('system','기관 구매·회계 절차 진행','기관에서 사용하는 구매·회계 시스템과 결재 절차를 확인해요. e-사람 복무 매뉴얼을 구매 근거로 사용하지 않아요.'),
              ('check','누락·처리 결과 확인','납품·검수·지급 중 현재 단계에 필요한 자료와 처리 결과를 확인해요.')],
    'education': [('scope','교육 안내 확인','교육명·일정·대상 부서·회신 마감을 확인해요.'),('materials','회신 서식 준비','기관 서식과 회신 요청문을 준비해요.'),('check','회신·누락 확인','희망자 없음 기록과 미회신·중복을 확인해요. 자료 취합 도구는 필요할 때 열 수 있어요.')],
}
MANUAL_QUERY = {'travel':'e-사람 출장 정산 내역 불러오는 방법', 'leave':'e-사람 근무상황 신청 입력 방법',
                'overtime':'e-사람 초과근무 신청 입력 방법','flex':'e-사람 유연근무 신청 입력 방법',
                'duty':'e-사람 당직 조회 방법','security':'e-사람 보안점검 등록 방법'}


def topic(query):
    return next(((key,label) for key,label,pattern in TOPICS if re.search(pattern,query)),('general','서무 업무'))


def effective_query(query, context):
    """Only short follow-ups inherit bounded user text; explicit new topics win."""
    if not isinstance(context,str) or len(context)>3000:return query
    if topic(query)[0]!='general':return query
    if re.search(r'^(?:(?:그럼|그러면|그리고|그런데|좋아|그거|이거)\s*)?(?:정산|계산|도와|기한|언제|서류|서식|어디|신청|숙박|차량|개인차량|자가용|\d+박)',query):
        lines=context.splitlines()
        anchor=next((i for i in range(len(lines)-1,-1,-1) if topic(lines[i])[0]!='general'),None)
        if anchor is not None:
            relevant='\n'.join(lines[anchor:])
            return (relevant[:max(0,2999-len(query))]+'\n'+query).strip()
    return query


def _forms(key,query=''):
    if key=='goods' and knowledge.relevance.is_budget_question(query):return []
    words={'travel':r'출장|여비|정산','leave':r'휴가|연가|복무|근무상황','goods':r'구매|물품|검수','education':r'교육|희망자'}.get(key)
    if not words:return []
    result=[]
    for f in store.list_forms():
        if not re.search(words,f['name']):continue
        document=store.get_document(f['doc_id']) if f.get('doc_id') else None
        result.append(dict(id=f['id'],name=f['name'],href=f"/api/documents/{f['doc_id']}/download" if document else 'index.html#forms',
                           synthetic=bool(re.search(r'모의|합성|예시|가상',f['name']+' '+(f.get('doc_title') or '')+' '+(f.get('doc_filename') or ''))),
                           source_id=f.get('doc_id'),sha256=(document or {}).get('sha256')))
    return result[:5]


def source_map(key,steps,evidence,manuals,forms):
    nodes=[dict(id='topic:'+key,label=key,kind='topic')];edges=[]
    for step in steps:
        node='step:'+key+':'+step['id'];nodes.append(dict(id=node,label=step['title'],kind='preparation'))
        edges.append(dict(source='topic:'+key,target=node,relation='준비 순서'))
    for ref in evidence+manuals:
        sid=ref.get('source_id') or ref['id'];node='source:'+sid+(':'+str(ref['page']) if ref.get('page') else '')
        if any(n['id']==node for n in nodes):continue
        nodes.append(dict(id=node,label=ref['title'],kind=ref.get('reference_kind','legal'),sha256=ref.get('sha256'),loc=ref.get('loc'),page=ref.get('page')))
        edges.append(dict(source='topic:'+key,target=node,relation='검색된 자료'))
    for form in forms:
        node='form:'+form['id'];nodes.append(dict(id=node,label=form['name'],kind='form',sha256=form.get('sha256')))
        edges.append(dict(source='topic:'+key,target=node,relation='등록 서식 후보'))
    return dict(nodes=nodes,edges=edges,note='자료의 관련을 보여줍니다. 법적 적용 관계를 자동 판정한 결과는 아닙니다.')


def respond(query,body,today):
    effective=effective_query(query,body.get('situation_context',''))
    key,label=topic(effective);library=body.get('knowledge_library_id') or None
    manual_plan=manual_knowledge.classify(effective)
    combined=bool(re.search(r'다녀|\d+\s*박|처리\s*순서|규정|근거|함께|방법과|방법도',effective))
    manual_only=manual_plan and manual_plan['kind']=='manual' and not combined
    if manual_only:
        found=dict(hits=[],experiences=[],excluded=[],intent=None)
        reply=dict(evidence=[],experiences=[],excluded=[],mode='source_search',model=None,answer='',notice='',scope='')
    else:
        if key=='general' and not knowledge.intent.analyze(effective):
            found=dict(hits=[],experiences=[],excluded=[],intent=None,unavailable_reason='이 질문에 직접 답하는 등록 근거를 확인하지 못했어요. 업무 종류와 관련 규정·지침을 알려주세요.')
        else:found=knowledge.retrieve(effective,library,today)
        reply=knowledge.answer(effective,found,use_ai=body.get('use_ai') is True)
        reply['tree']=answer_tree.build(effective,reply)
    manual_query=effective if manual_only else MANUAL_QUERY.get(key,'')
    if key=='travel' and re.search(r'신청|출장\s*전|출장계획',effective) and not re.search(r'정산|다녀',effective):manual_query='e-사람 출장 신청 입력 방법'
    if key=='leave' and not manual_only:
        subtype=next((s for s in ('배우자출산휴가','출산휴가','경조사휴가','특별휴가','병가','공가','대체휴무','연가','포상휴가') if s in effective.replace(' ','')),None)
        if subtype:manual_query=f'e-사람 {subtype} 신청 입력 방법'
    manual=manual_knowledge.respond(manual_query,library) if manual_query else None
    manual_k=(manual or {}).get('knowledge',{})
    manuals=[e for e in manual_k.get('evidence',[]) if e.get('reference_kind')=='system_manual']
    defaults=[('scope','상황과 적용 기준 확인','기관·업무 종류와 현재 처리 단계를 알려주세요.'),('materials','근거·서식 확인','질문에 직접 답하는 규정·지침·매뉴얼을 등록하면 원문을 확인할 수 있어요.')]
    steps=[dict(id=sid,title=title,detail=detail,kind='preparation') for sid,title,detail in PREPARATION.get(key,defaults)]
    questions=[]
    if key=='travel':
        if not re.search(r'\d{4}[-./년]\s*\d',effective):questions.append('실제 출장 시작일과 종료일을 알려주세요. 2박 3일만으로 날짜를 정하지 않아요.')
        if not re.search(r'국가공무원|지방공무원|소방공무원|국가기관|지방자치단체',effective):
            questions.append('소속 기관과 적용 신분을 확인해 주세요. 국가·지방·기관별 기준이 다를 수 있어요.')
    elif key=='leave':questions.append('휴가 종류·사유, 적용 신분과 소속 기관을 확인해 주세요.')
    elif key=='goods':questions.append('소속 기관·회계 구분, 적용 연도와 구매 품목을 확인해 주세요.')
    elif key=='general':questions.append('어떤 서무업무인지, 지금 무엇을 처리하려는지 알려주세요.')
    tree=reply.get('tree') or {};deadlines=[]
    for branch in tree.get('branches',[]):
        if re.search(r'기한|언제|기간',branch['label']):
            deadlines.extend(dict(text=i['text'],ref=i.get('ref')) for i in branch['items'])
    forms=_forms(key,effective)
    guide=dict(topic=key,title=label+' 처리 방법',context=effective,questions=questions,steps=steps,deadlines=deadlines,forms=forms,
               manual=dict(evidence=manuals,scope=manual_k.get('scope',''),notice=manual_k.get('notice','') if manual_query else '이 업무에 맞는 시스템 매뉴얼을 등록하면 사용법을 연결할 수 있어요.'),
               ai_requested=body.get('use_ai') is True,ai_used=reply.get('mode')=='source_llm',
               notice='진행 순서는 실무 준비 제안입니다. 법정 기한·필수 서류·적용 조건은 아래 등록 근거에서 확인하세요.')
    guide['map']=source_map(key,steps,reply.get('evidence',[]),manuals,forms)
    result=dict(query=effective,mode='structured_guidance',model=reply.get('model'),profile=None,summary='등록 자료로 처리 방법을 함께 확인해요.',
                answer=reply.get('answer',''),notice=reply.get('notice',''),plan=None,alternatives=[],cited=[],related=[],personal_notes=[],knowledge=reply,guidance=guide)
    action=task_intent.action(effective)
    if action:result['task_action']=action
    return result
