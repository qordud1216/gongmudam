"""Conservative lexical relevance checks; no legal conclusions or entitlement rates."""
import re
from . import knowledge_intent as intent

FACETS = {
    '출장': ('출장', '여비'), '정산': ('정산', '증거서류', '영수증'),
    '근무지 내 출장': ('근무지내', '관내출장'),
    '공무용 차량': ('공무용차량', '공용차량', '관용차량'),
    '일비': ('일비',), '숙박비': ('숙박비', '숙박료'), '식비': ('식비',), '운임': ('운임', '교통비'),
    '연가': ('연가', '연차'), '병가': ('병가',), '공가': ('공가',),
    '특별휴가': ('특별휴가', '특가'), '출산휴가': ('출산휴가',), '육아시간': ('육아시간',),
    '가족돌봄': ('가족돌봄',), '건강검진': ('건강검진', '건강진단'),
    '헌혈': ('헌혈',), '대체휴무': ('대체휴무', '대체휴가'),
    '물품': ('물품', '사무용품', '납품'), '검사': ('검사', '검수'),
    '예산 과목': intent.BUDGET_TERMS,
    '대가': ('대가', '대금'), '수의계약': ('수의계약',), '불용': ('불용', '폐기'),
    '포인트': ('포인트',), '집행 공개': ('집행내역공개', '집행현황공개', '집행현황의공개', '집행내역의공개'),
    '초빙강사료': ('초빙강사료',), '위험수당': ('위험수당',),
    '교육 취합': ('교육희망자', '교육참석자', '참석희망자', '교육생명단', '교육명단', '희망자취합', '참석자모집', '참가자명단'),
}
BROAD = {'출장', '물품'}

def flat(text):
    return re.sub(r'\s+', '', text)


def is_budget_question(query):
    return any(alias in flat(query) for alias in FACETS['예산 과목'])


def budget_topics(query):
    q=flat(query)
    aliases={
        'office_supplies': ('사무용품','필기구','용지','볼펜','문구류','사무소모품','사무용소모품','사무관리비','일반수용비','201-01','일반운영비'),
        'assets': ('컴퓨터','프린터','책상','의자','비품','모니터','복사기','냉장고','자산취득','자산및물품','405-01','자산성'),
    }
    topics={topic for topic,terms in aliases.items() if any(t in q for t in terms)}
    if any(t in q for t in ('토너','잉크','카트리지')):
        topics.discard('assets');topics.add('office_supplies')
    elif any(t in q for t in ('수리비','수선비','임차료','임대료','렌탈','유지보수','설치비')):
        # The device name alone does not establish acquisition expenditure.
        topics.discard('assets')
    return topics


def budget_evidence(hit):
    text=flat(hit['title']+' '+hit['text'])
    # '예산' mentioned incidentally in a contract/inspection article is not a budget classification.
    return any(t in text for t in ('사무관리비','일반수용비','자산및물품취득비','201-01','405-01')) and any(
        t in text for t in ('예산편성','집행기준','예산과목','통계목','편성목','회계관리'))


def budget_scope_reason(query, source, today):
    official=source.get('official') or {}
    if not is_budget_question(query) or not official.get('budget_scope'):
        return ''
    q=flat(query)
    if official['budget_scope']=='local_government' and any(t in q for t in ('국가기관','중앙부처','국가예산','국가회계','교육청','학교회계','교육비특별회계','공기업')):
        return '질문한 기관·회계 구분에 맞는 예산 과목 기준이 필요합니다.'
    years=official.get('fiscal_years',[])
    requested={int(y) for y in re.findall(r'(?<!\d)(20\d{2})(?!\d)',query)} or {today.year}
    missing=requested-set(years)
    if years and missing:
        return ', '.join(str(y) for y in sorted(missing))+'년도 예산에 적용할 과목 기준이 필요합니다. 등록한 자료는 '+', '.join(str(y) for y in years)+'년도 자료입니다.'
    return ''

def facets(text):
    text=flat(text)
    return {key for key,aliases in FACETS.items() if any(alias in text for alias in aliases)}

def expanded_query(query):
    # Aliases expand retrieval terms, never the quoted source text.
    focus=budget_topics(query) if is_budget_question(query) else set()
    extra=(' 기본사무용품비 필기구' if 'office_supplies' in focus else '')+(' 자산및물품취득비' if 'assets' in focus else '')
    return query+' '+' '.join(FACETS[key][0] for key in sorted(facets(query)))+extra+' '+intent.expanded_terms(intent.analyze(query))

def filter_hits(query,hits,plan=None):
    plan=plan or intent.analyze(query)
    if plan:return intent.filter_hits(query,hits,plan)
    wanted=facets(query); specific=wanted-BROAD;q=flat(query)
    domains=set()
    if '출장' in wanted or wanted&{'일비','숙박비','식비','운임','근무지 내 출장'}:domains.add('travel')
    if wanted&{'연가','병가','공가','특별휴가','출산휴가','육아시간','가족돌봄','건강검진','헌혈','대체휴무'}:domains.add('leave')
    if wanted&{'물품','수의계약','불용'}:domains.add('goods')
    candidates=[]
    for h in hits:
        official=h.get('official') or {}; title=official.get('title',''); article=official.get('article','')
        if official.get('budget_scope') and '예산 과목' not in wanted:continue
        if official.get('budget_topics') and not set(official['budget_topics'])&budget_topics(query):continue
        if any(t in q for t in ('국가공무원','국가직','중앙부처')) and ('지방공무원' in title or '지방자치단체' in title):continue
        if '예산 과목' in wanted and not budget_evidence(h):continue
        if domains and title:
            domain='travel' if '여비' in title else 'leave' if '복무' in title else 'goods' if '계약' in title else None
            if domain and domain not in domains:continue
        # A cross-reference inside a different leave article is not a direct answer.
        kinds=wanted&{'연가','병가','공가'}
        if len(kinds)==1 and '복무' in title and not (facets(article)&kinds):continue
        covered=facets(h['text']+' '+h['title'])&wanted
        if specific and not covered&specific:continue
        if wanted and not covered:continue
        weight=len(covered&specific)*3+len(covered&BROAD)+len(facets(article)&specific)*3
        candidates.append((weight,h,covered))
    if not candidates:
        return [],('등록 원문에서 예산 과목에 관한 직접 근거를 확인할 수 없습니다. 적용 기관·회계·연도에 맞는 예산편성 또는 집행기준을 확인해 주세요.'
                   if '예산 과목' in wanted else '등록 원문에서 질문의 핵심 항목을 확인할 수 없습니다.')
    best=max(c[0] for c in candidates)
    candidates=[c for c in candidates if not wanted or c[0]>=max(1,best*.6)]
    candidates.sort(key=lambda c:(c[0],c[1]['score']),reverse=True)
    covered=set().union(*(c[2] for c in candidates))
    missing=specific-covered
    if missing:return [],'등록 원문에서 '+', '.join(sorted(missing))+'에 관한 직접 근거를 확인할 수 없습니다.'
    selected=[]
    for _,h,_ in candidates:
        if any(e['source_id']==h['source_id'] for e in selected):continue
        selected.append(h)
        if len(selected)==3:break
    return selected,''

def missing_reference(query,hits):
    q=flat(query)
    if any(t in q for t in ('지방공무원','지방직')) and any((h.get('official') or {}).get('title')=='공무원 여비 규정' for h in hits):
        if not any('여비' in h['title'] and '조례' in h['title'] for h in hits):return '해당 지방자치단체 여비 조례의 준용·지급 기준이 등록되지 않아 지방공무원에게 적용할 금액을 확정할 수 없습니다.'
    amount=intent.amount_question(query)
    if amount and any(t in q for t in ('숙박','호텔','일비','식비','식대')) and any('별표 2' in h['text'] for h in hits):
        from . import knowledge_supplement
        annex='별표 4' if knowledge_supplement.foreign_query(query) else '별표 2'
        if not any(annex in h['title'] for h in hits):return f'여비 금액표인 {annex}가 등록되지 않아 숙박비·일비·식비의 기준 금액을 확인할 수 없습니다.'
    duration=any(t in q for t in ('며칠','몇일','일수','기간'))
    if (intent.analyze(query) or {}).get('topics')==['occasion'] or '배우자출산' in q or duration and any(t in q for t in ('경조사','결혼휴가')):
        special=any((h.get('official') or {}).get('title')=='지방공무원 복무규정' and (h.get('official') or {}).get('article','').startswith('제7조의7') for h in hits)
        if (special or any('별표 1' in h['text'] for h in hits)) and not any('별표' in h['title'] for h in hits):return '경조사휴가 일수표인 별표 1이 등록되지 않아 일수를 확인할 수 없습니다.'
    return ''

def legal_windows(units):
    """Keep complete paragraphs and their following exceptions/subparagraphs together."""
    text='\n'.join(u['text'] for u in units)
    if len(text)<=2000:return [{'text':text,'loc':f'1~{len(units)}행'}]
    starts=sorted({0}|{m.start() for m in re.finditer(r'(?m)^[②-⑳]',text)})
    ends=starts[1:]+[len(text)];out=[]
    for i,start in enumerate(starts):
        end=ends[i]
        for following in ends[i+1:]:
            if following-start>2000:break
            end=following
        out.append({'text':text[start:end].rstrip('\n'),'loc':f'{text[:start].count(chr(10))+1}~{text[:end].count(chr(10))+1}행'})
    return out

def original_answer(query,evidence):
    from .search import BM25
    plan=intent.analyze(query)
    if plan and plan['status']=='ready':
        # Retrieval has already selected complete, directly relevant legal windows.
        # A second keyword ranking can drop a requested deadline or an exception,
        # especially when two questions refer to different parts of the same rule.
        return '\n\n'.join(f'[{i}] '+h['text'] for i,h in enumerate(evidence,1))
    lines=[]
    for i,h in enumerate(evidence,1):
        blocks=re.split(r'\n(?=[①-⑳])',h['text'])
        if len(blocks)==1 and '\n' in h['text']:
            blocks=h['text'].splitlines()
        scores=BM25(blocks).top(expanded_query(query),k=2,min_score=0)
        chosen={index for index,_ in scores}
        if re.match(r'^제\d+조',blocks[0]) and '①' in blocks[0]:chosen.add(0)
        if any(re.match(r'^\d+\.',blocks[index]) for index in chosen):chosen.add(0)
        for index in sorted(chosen):lines.append(f'[{i}] '+blocks[index])
    return '\n\n'.join(lines)
