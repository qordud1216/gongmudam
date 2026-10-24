"""Readable, reviewed explanations tied to exact source versions and support quotes.

This presentation layer neither changes retrieval nor calculates entitlements.
Unknown or changed source versions receive a source-navigation tree instead.
"""
import json
from functools import lru_cache
from pathlib import Path
from . import official_sources, knowledge_relevance as relevance
from . import knowledge_intent as intent

RULES=Path(__file__).resolve().parents[1]/'reference_data/easy_summaries_v35.json'

@lru_cache(maxsize=1)
def rules():
    try:return json.loads(RULES.read_text(encoding='utf-8'))['rules']
    except (OSError,ValueError,KeyError):return []

def build(query,reply):
    evidence=reply.get('evidence',[])
    plan=reply.get('intent') or intent.analyze(query)
    note='이해를 돕는 요약이에요. 내 기관에 적용되는 조건은 근거에서 확인하세요.'
    if not evidence:
        reason=reply.get('notice','')
        if (plan or {}).get('status')=='clarify':
            return dict(kind='clarification',title='상황을 조금만 더 알려주세요',branches=[
                dict(label='먼저 확인할 내용',items=[dict(text=plan['question'],ref=None)])],note='확인되지 않은 상황에 다른 업무의 기준을 적용하지 않아요.')
        if relevance.is_budget_question(query):
            missing='질문한 예산 과목을 뒷받침하는 자료가 아직 없어요.'; action='기관·회계 구분과 적용 연도에 맞는 예산편성·집행기준을 등록해 주세요.'
        elif '별표 2' in reason:
            missing='출장비 금액이 적힌 표가 아직 없어요.'; action='여비 금액표(별표 2)를 등록해 주세요.'
        elif '별표 4' in reason:
            missing='국외 출장비 금액표가 아직 없어요.'; action='국외 여비 금액표(별표 4)를 등록해 주세요.'
        elif '별표 1' in reason:
            missing='경조사휴가의 일수가 적힌 표가 아직 없어요.'; action='경조사휴가 일수표(별표 1)를 등록해 주세요.'
        elif '여비 조례' in reason:
            missing='소속 지자체의 출장비 기준이 아직 없어요.'; action='해당 지자체의 여비 조례를 등록해 주세요.'
        else:
            missing=reason or '질문에 맞는 근거를 등록 자료에서 찾지 못했어요.'; action='국가·지방 등 적용 대상과 등록 자료를 확인해 주세요.'
        return dict(kind='unavailable',title='자료를 더 확인해야 답할 수 있어요',branches=[
            dict(label='어떤 자료가 필요한가요?',items=[dict(text=missing,ref=None)]),
            dict(label='지금 할 일',items=[dict(text=action,ref=None),dict(text='자료를 등록한 뒤 같은 질문을 다시 해보세요.',ref=None)])],note='질문에 직접 답하는 원문을 확인한 뒤 안내할게요.')
    q=''.join(query.split())
    from . import knowledge_supplement
    extended=knowledge_supplement.summary(query,reply)
    if extended:return extended
    for index,h in enumerate(evidence,1):
        if not h.get('official') or not official_sources.metadata(h.get('sha256')):continue
        for rule in rules():
            if relevance.is_budget_question(query) and not rule['id'].startswith('budget-'):continue
            if rule['id'].startswith('budget-') and not relevance.is_budget_question(query):continue
            if not intent.summary_allowed(rule['id'],query,plan):continue
            if rule['sha256']!=h.get('sha256'):continue
            if rule.get('when_any') and not any(term in q for term in rule['when_any']):continue
            if any(term in q for term in rule.get('unless_any',[])):continue
            if any(not any(term in q for term in group) for group in rule.get('when_all_groups',[])):continue
            excluded_groups=rule.get('unless_all_groups',[])
            if excluded_groups and all(any(term in q for term in group) for group in excluded_groups):continue
            nodes=[item for branch in rule['branches'] for item in branch['items']]
            # Never drop an unsupported exception from a curated explanation.
            if not nodes or any(not item.get('requires') or not all(quote in h['text'] for quote in item['requires']) for item in nodes):continue
            branches=[dict(label=b['label'],items=[dict(text=i['text'],ref=index,support_quotes=i['requires']) for i in b['items']]) for b in rule['branches']]
            return dict(kind='summary',title=rule['title'],branches=branches,note=rule.get('note',note),rule_id=rule['id'],reviewed_source_sha256=rule['sha256'])
    return dict(kind='extract',title='찾은 자료를 차례로 확인해요',branches=[
        dict(label='관련 자료',items=[dict(text=h['title'],ref=i) for i,h in enumerate(evidence,1)]),
        dict(label='지금 할 일',items=[dict(text='근거 버튼을 눌러 질문에 맞는 조항과 적용 조건을 확인해 보세요.',ref=None)])],note='이 자료는 아직 쉬운 설명이 준비되지 않았어요. 원문을 펼쳐 확인할 수 있어요.')
