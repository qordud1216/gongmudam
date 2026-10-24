"""Question intent and direct-source coverage. Never infers an allowance or leave entitlement."""
import re
from . import knowledge_supplement as supplement


def flat(text):
    return re.sub(r'\s+', '', text)


BUDGET_TERMS = ('예산과목','예산목','예산항목','통계목','편성목','세목','세출과목','무슨목','어느목','어떤목',
    '어느과목','어떤과목','무슨과목','어떤예산','어느예산','무슨예산','어디예산','사무관리비','일반수용비',
    '일반운영비','자산취득비','자산및물품취득비','201-01','405-01')


# Synonyms concern the question only; cited text is never rewritten.
TOPICS = {
    'travel_rate_domestic': ('국내 여비 금액표', ('숙박비','일비','식비')),
    'travel_rate_foreign': ('국외 여비 금액표', ('국외','숙박비','일비','식비')),
    'travel_group': ('여비 지급 구분표', ('지급구분','제2호','제1호')),
    'travel_fuel_details': ('자가용 연료비의 세부 산정 기준', ('연료비','킬로','계산')),
    'travel_provided_meals': ('식사 제공 시 식비 감액 기준', ('식사제공','급식','식비감액')),
    'occasion_use': ('경조사휴가 사용기한·분할 기준', ('경조사','사용기한','분할')),
    'goods_inspection_deadline': ('납품검사의 완료 기한', ('검사','검수','기한')),
    'travel_settlement': ('출장 정산·증빙', ('정산','영수증','증빙','증거서류')),
    'travel_card': ('출장비 결제 방법', ('카드','현금','결제')),
    'travel_local': ('근무지 내 출장', ('근무지내','관내','같은시군','같은시·군','12킬로','12km')),
    'travel_daily': ('일비 지급', ('일비',)),
    'travel_lodging': ('숙박비 지급', ('숙박비','숙박료','호텔비')),
    'travel_meal': ('식비 지급', ('식비','식대')),
    'travel_extra': ('여비 초과지출·추가 정산', ('추가정산','초과지출','부득이')),
    'travel_private_car': ('자가용 운임·연료비', ('자가용','기름값','주유비','연료비','내차')),
    'travel_taxi': ('출장 택시비', ('택시',)),
    'travel_flight': ('항공 운임·좌석 등급', ('항공권','비즈니스석','비지니스석','일등석')),
    'travel_mileage': ('공무 항공 마일리지', ('마일리지',)),
    'travel_education': ('선발된 교육출장의 세부 기준', ('교육대상자','교육출장')),
    'travel_risk': ('출장 관련 위험수당', ('위험수당',)),
    'travel_general': ('질문한 직군의 여비 기준', ('여비','출장')),
    'travel_foreign_local': ('국외 근무지 내 출장 기준', ('국외','해외')),
    'annual': ('연가 일수·재직기간', ('연가','연차')),
    'annual_use': ('연가 사용·승인 절차', ('반일','반차','승인','허가절차','이월','저축')),
    'sick': ('병가', ('병가',)),
    'public_health': ('법정 건강검진 공가', ('건강검진','건강진단','국가검진')),
    'public_blood': ('헌혈 공가', ('헌혈',)),
    'public_leave': ('공가 사유', ('공가',)),
    'childcare': ('육아시간', ('육아시간',)),
    'family_care': ('가족돌봄휴가', ('가족돌봄','가족돌봄휴가')),
    'maternity': ('본인 출산휴가', ('출산휴가',)),
    'pregnancy_check': ('임신검진휴가', ('임신검진','임신중검진')),
    'pregnancy_accompany': ('임신검진 동행휴가', ('임신검진동행','검진동행휴가')),
    'maternal_time': ('모성보호시간', ('모성보호시간',)),
    'miscarriage': ('유산·사산휴가', ('유산휴가','사산휴가')),
    'fertility': ('난임치료시술휴가', ('난임',)),
    'women_health': ('여성보건휴가', ('여성보건휴가','생리휴가')),
    'disaster_leave': ('재해구호휴가', ('재해구호휴가',)),
    'mental_leave': ('심리안정휴가', ('심리안정휴가',)),
    'occasion': ('경조사휴가 일수표', ('배우자출산','아내출산','와이프출산','경조사','결혼','사망')),
    'compensatory': ('대체휴무', ('대체휴무','대체휴가')),
    'goods_inspection': ('물품 검사·검사조서', ('검수','검사','검사조서')),
    'goods_inspection_limit': ('검사조서 생략 금액', ('검사조서','생략')),
    'goods_payment': ('대금 지급·선금 예외', ('대금','대가','선금','돈부터','돈을먼저','돈먼저')),
    'goods_payment_deadline': ('대가 지급의 구체적인 기한', ('대금','대가')),
    'goods_payment_interest': ('대가 지급 지체이자의 법적 근거', ('지체일수','이자')),
    'goods_quote': ('견적서·견적 비교', ('견적',)),
    'goods_private_contract': ('수의계약 한도·조건', ('수의계약',)),
    'goods_disposal': ('불용·폐기', ('불용','폐기')),
    'goods_defect': ('불량품 반품·교환', ('불량','반품','교환')),
    'account_points': ('업무 구매 인센티브 처리', ('포인트','적립금','마일리지','인센티브')),
    'account_lecturer': ('초빙강사료 집행 공개', ('초빙강사료','초빙강연료')),
    'account_disclosure': ('업무추진비 집행 공개의 별표', ('업무추진비',)),
    'account_incentive_disclosure': ('인센티브 세입·집행내역 공개', ('인센티브','세입조치')),
    'account_retirement_disclosure': ('장기근속·퇴직자 집행내역 공개', ('장기근속','퇴직')),
}
SPECIAL = {'childcare':'육아시간','family_care':'가족돌봄휴가','maternity':'출산휴가',
    'pregnancy_check':'임신검진휴가','pregnancy_accompany':'임신검진동행휴가','maternal_time':'모성보호시간',
    'miscarriage':'유산휴가','fertility':'난임치료시술휴가','women_health':'여성보건휴가',
    'disaster_leave':'재해구호휴가','mental_leave':'심리안정휴가','occasion':'경조사휴가'}
ARTICLE = {
    'travel_settlement': ('공무원 여비 규정','제8조의2('), 'travel_card': ('공무원 여비 규정','제8조의2('),
    'travel_local': ('공무원 여비 규정','제18조('),
    **{t:('공무원 여비 규정','제16조(') for t in ('travel_daily','travel_lodging','travel_meal','travel_extra')},
    'annual': ('지방공무원 복무규정','제7조('), 'sick': ('지방공무원 복무규정','제7조의5('),
    **{t:('지방공무원 복무규정','제7조의6(') for t in ('public_health','public_blood','public_leave')},
    **{t:('지방공무원 복무규정','제7조의7(') for t in SPECIAL},
    'goods_inspection': ('지방자치단체를 당사자로 하는 계약에 관한 법률','제17조('),
    'goods_payment': ('지방자치단체를 당사자로 하는 계약에 관한 법률','제18조('),
    'goods_payment_interest': ('지방자치단체를 당사자로 하는 계약에 관한 법률','제18조('),
    'account_points': ('지방자치단체 회계관리에 관한 훈령','제120조('),
    'account_lecturer': ('지방자치단체 회계관리에 관한 훈령','제121조('),
    'account_incentive_disclosure': ('지방자치단체 회계관리에 관한 훈령','제121조('),
    'account_retirement_disclosure': ('지방자치단체 회계관리에 관한 훈령','제121조('),
}
MISSING = {
    'travel_rate_domestic':'국내 여비 금액표인 별표 2와 지급 근거 제16조를 함께 등록해야 합니다.',
    'travel_rate_foreign':'국외 여비 금액표인 별표 4와 지급 근거 제16조를 함께 등록해야 합니다.',
    'occasion':'경조사휴가 일수를 확인할 별표 1이 필요합니다.',
    'goods_inspection_limit':'검사조서 작성 생략 금액을 정한 시행령 등 직접 기준이 필요합니다.',
    'goods_payment_deadline':'대가 지급의 구체적인 기한을 정한 시행령 등 직접 기준이 필요합니다.',
    'account_disclosure':'업무추진비 공개 항목·주기·시기를 정한 별표 2의2가 필요합니다.',
    'travel_education':'교육대상자로 선발된 출장에 적용하는 인사혁신처 세부 기준이 필요합니다.',
}


def amount_question(query):
    q=flat(query)
    if any(t in q for t in ('퍼센트','몇%','비율')):return False
    if any(t in q for t in ('기한','언제까지','얼마나빨리')) and not re.search(r'얼마(?!나빨리)|몇원|금액은',q):
        return False
    return bool(re.search(r'얼마(?!나빨리)|몇(?:만)?원|금액|지급액|기준액|상한|한도',q))


def analyze(query):
    q=flat(query)
    # The separately scoped budget-table matcher remains responsible for budget questions.
    if any(t in q for t in BUDGET_TERMS):
        if any(t in q for t in ('병가','연가','출장','출산휴가')) and any(t in q for t in ('각각','둘다','함께','이랑','비교')):
            return dict(topics=[],status='clarify',question='예산 과목과 다른 업무는 적용 자료가 달라요. 질문을 하나씩 나누어 알려주세요.',recognized=True,labels=[])
        return None
    travel=any(t in q for t in ('출장','여비','외근','일비','숙박비','숙박료','호텔비','기름값','택시비','주유비','항공권'))
    leave=any(t in q for t in ('휴가','휴무','연가','연차','병가','공가','육아시간','모성보호'))
    goods=any(t in q for t in ('물품','납품','검수','검사조서','수의계약','불용','견적','법인카드','문구점','인센티브','포인트','적립금','마일리지','강사료','강연료','업무추진비','지방자치단체선금','퇴직예정자기념품'))
    topics=[];question=''
    def add(topic):
        if topic not in topics:topics.append(topic)
    if travel:
        for t in ('travel_private_car','travel_taxi','travel_flight','travel_mileage','travel_risk'):
            if any(a in q for a in TOPICS[t][1]):add(t)
        if ('교육대상자' in q or '교육출장' in q) and any(t in q for t in ('선발','세부기준','지급기준')):add('travel_education')
        if 'travel_private_car' in topics and (amount_question(query) or any(t in q for t in ('계산','리터','킬로','km','연비'))):
            topics.remove('travel_private_car');add('travel_fuel_details')
        if not topics:
            lodging=any(t in q for t in ('숙박','호텔'))
            meal=any(t in q for t in ('식비','식대'))
            extra=(lodging or meal) and any(t in q for t in ('초과','추가정산','부득이'))
            local=any(t in q for t in TOPICS['travel_local'][1])
            if any(t in q for t in ('지급구분','몇호','1호인지','2호인지')):add('travel_group')
            elif any(t in q for t in ('지급표','금액표','별표2','별표4')):
                add('travel_rate_foreign' if supplement.foreign_query(query) or '별표4' in q else 'travel_rate_domestic')
            elif extra:add('travel_extra')
            elif local:
                add('travel_foreign_local' if any(t in q for t in ('국외','해외','미국','외국','일본','중국')) else 'travel_local')
                if any(t in q for t in TOPICS['travel_settlement'][1]):add('travel_settlement')
            elif any(t in q for t in ('현금','카드','결제')):add('travel_card')
            elif any(t in q for t in ('정산','영수증','증빙','증거서류')):add('travel_settlement')
            elif '일비' in q:add('travel_daily')
            elif lodging:add('travel_lodging')
            elif meal:add('travel_meal')
            elif any(t in q for t in ('군인','공무직','교육공무원','교사','공기업')):add('travel_general')
            else:question='출장의 어떤 부분이 궁금한가요? 정산 기한·증빙, 관내 여비, 일비 감액 등 처리할 내용을 알려주세요.'
        if any(t in q for t in ('각각','둘다','함께','이랑','비교','일비와','숙박비와','숙박비상한과')):
            if 'travel_local' not in topics and 'travel_extra' not in topics:
                for t in ('travel_daily','travel_lodging','travel_meal','travel_settlement'):
                    if any(a in q for a in TOPICS[t][1]):add(t)
        rates=set(topics)&{'travel_daily','travel_lodging','travel_meal'}
        if rates and amount_question(query) and 'travel_extra' not in topics:
            topics[:]=[t for t in topics if t not in rates]
            add('travel_rate_foreign' if supplement.foreign_query(query) else 'travel_rate_domestic')
        if any(t in q for t in ('식비','식사','급식')) and any(t in q for t in ('제공','무료','포함','급식')):
            topics[:]=[t for t in topics if t not in ('travel_meal','travel_rate_domestic','travel_rate_foreign')]
            add('travel_provided_meals')
    if leave:
        # A stated purpose takes precedence over alternatives mentioned for comparison ('연가 대신 공가').
        for t in ('childcare','family_care','maternal_time','pregnancy_accompany','pregnancy_check','miscarriage','fertility','women_health','disaster_leave','mental_leave'):
            if any(a in q for a in TOPICS[t][1]):add(t)
        if 'pregnancy_accompany' in topics and 'pregnancy_check' in topics:topics.remove('pregnancy_check')
        if any(t in q for t in ('배우자','아내','와이프')) and any(t in q for t in ('산전검진','임신검진')) and '동행' in q:
            add('pregnancy_accompany')
            if 'pregnancy_check' in topics:topics.remove('pregnancy_check')
        if any(t in q for t in ('유산','사산')):add('miscarriage')
        if any(t in q for t in ('자녀','아이','손자녀')) and any(t in q for t in ('검진','진료','예방접종','상담')):add('family_care')
        if not any(t in SPECIAL for t in topics) and any(t in q for t in ('배우자','아내','와이프')) and '출산' in q:add('occasion')
        if not any(t in SPECIAL for t in topics) and any(t in q for t in ('경조사','결혼','사망','입양','돌아가셨','돌아가신','부친상','모친상','장례')):add('occasion')
        if 'occasion' in topics and any(t in q for t in ('사용기한','분할','나눠','언제까지')):
            topics.remove('occasion');add('occasion_use')
        if not any(t in SPECIAL for t in topics) and '출산' in q:add('maternity')
        if not any(t in SPECIAL for t in topics):
            if '연가' in q and '병가' in q and any(t in q for t in ('가산','더해','추가','안썼','미사용','사용하지않','22일')):add('annual')
            elif any(a in q for a in TOPICS['public_health'][1]):add('public_health')
            elif '헌혈' in q:add('public_blood')
            elif '병가' in q:add('sick')
            elif any(t in q for t in ('대체휴무','대체휴가')):add('compensatory')
            elif any(t in q for t in ('연가','연차')):
                if any(t in q for t in ('남은','남았','잔여','잔량')) and not any(t in q for t in ('근거','규정','이월','보상')):question='개인의 남은 연가는 규정만으로 알 수 없어요. 올해 부여·이월·사용한 연가 내역을 확인해 주세요.'
                elif any(t in q for t in TOPICS['annual_use'][1]) and not any(t in q for t in ('보상','재직기간')):add('annual_use')
                else:add('annual')
            elif '공가' in q:
                if any(t in q for t in ('병원','진료')):question='어떤 사유의 방문인가요? 본인 진료, 법정 건강검진, 가족 진료 동행은 적용 기준이 달라요.'
                else:add('public_leave')
            else:question='어떤 휴가·휴무인지 알려주세요. 연가·병가·공가·특별휴가·대체휴무 중 종류와 사유를 확인해야 해요.'
        if 'sick' in topics and any(t in q for t in ('연가기본일수','연가일수표','연가일수와','연가와병가','연가및병가')):add('annual')
        if any(t in q for t in ('각각','둘다','비교','연가와','연가및','병가와','병가및')):
            if '연가' in q:add('annual')
            if '병가' in q:add('sick')
    if goods and not (travel and not any(t in q for t in ('물품','납품','검수','견적'))):
        if any(t in q for t in ('집행','공개')) and any(t in q for t in ('강사료','강연료','업무추진비')):
            add('account_disclosure' if '업무추진비' in q else 'account_lecturer')
        elif '공개' in q and any(t in q for t in TOPICS['account_points'][1]):add('account_incentive_disclosure')
        elif '공개' in q and '퇴직' in q:add('account_retirement_disclosure')
        elif any(t in q for t in TOPICS['account_points'][1]):add('account_points')
        else:
            goods_start=len(topics)
            for t in ('goods_quote','goods_private_contract','goods_disposal','goods_defect'):
                if any(a in q for a in TOPICS[t][1]):add(t)
            if 'goods_quote' in topics and 'goods_private_contract' in topics and not any(t in q for t in ('수의계약한도','수의계약가능금액','수의계약요건')):topics.remove('goods_private_contract')
            if len(topics)==goods_start:
                pay=any(t in q for t in ('대금','대가','선금','돈부터','돈을먼저','돈먼저'))
                inspect=any(t in q for t in ('검사','검수','검사조서','품질인증','성능시험'))
                if pay:
                    if '이자' in q:add('goods_payment_interest')
                    elif any(t in q for t in ('며칠','몇일','기한','언제까지','몇영업일')) or re.search(r'\d+(?:영업)?일(?:안|내|이내)',q):add('goods_payment_deadline')
                    else:add('goods_payment')
                    if inspect and any(t in q for t in ('검사와','검수와','검사및','검수및','각각','같이','둘다')):add('goods_inspection')
                elif inspect:
                    skip=any(t in q for t in ('생략','안써도','안작성','작성하지않','생략해도'))
                    money=amount_question(query) or bool(re.search(r'\d+[만천억,]*원',q))
                    if skip and money:add('goods_inspection_limit')
                    elif any(t in q for t in ('며칠','몇일','기한','언제까지')):add('goods_inspection_deadline')
                    else:add('goods_inspection')
                else:question='물품 구매의 어떤 단계인가요? 예산 과목, 견적·계약, 납품 검사, 대금 지급 중 궁금한 부분을 알려주세요.'
    if not (travel or leave or goods) and (re.search(r'^(?:그럼|그러면|그거|그건|그것|이거)',q) or '검사' in q or '재직기간' in q):
        question='어떤 업무와 상황인지 함께 알려주세요. 다른 업무의 기준을 임의로 적용하지 않을게요.'
    elif not (travel or leave or goods):
        return None
    if supplement.national(query) and any(t in q for t in ('지방공무원','지방직','지자체','지방자치단체')):
        question='국가기관과 지방기관의 기준은 적용 범위가 달라요. 기관별 질문을 나누어 알려주시면 각각 맞는 근거로 확인할게요.'
    return dict(topics=topics,status='clarify' if question else 'ready',question=question,
                recognized=True,labels=[TOPICS[t][0] for t in topics])


def expanded_terms(plan):
    return ' '.join(a for t in (plan or {}).get('topics',[]) for a in TOPICS[t][1][:2])


def scope_reason(query, source, today):
    official=source.get('official') or {}
    q=flat(query);title=official.get('title','') or source.get('title','')
    scope=flat(title+' '+source.get('institution',''))
    # Mentioning a child's teacher does not make the questioner a teacher.
    employee_q=re.sub(r'(?:담임)?교사(?:와의|와|상담)', '',q)
    jobs=('군인','공무직','교육공무원','교사','교원','공기업','사기업','민간기업','회사원')
    requested=[t for t in jobs if t in employee_q]
    if requested and not any(t in scope for t in requested):
        return '질문한 직군·기관에 적용할 별도의 근거가 필요합니다.'
    if any(t in q for t in ('국가기관','국가공무원','국가직','중앙부처','국가회계')) and any(t in scope for t in ('지방공무원','지방자치단체','교육청','학교')) and '국가공무원' not in scope:
        return '국가기관·국가공무원에 적용할 근거가 필요합니다.'
    if supplement.local(query) and '국가공무원복무규정' in flat(title):return '지방공무원에게 국가공무원 복무규정을 대신 적용하지 않습니다.'
    years={int(y) for y in re.findall(r'(?<!\d)(20\d{2})(?!\d)',query)}
    if years and min(years)<int(source.get('effective_date','0000')[:4] or 0):
        return '질문한 과거 시점에 시행된 원문이 필요합니다. 현재 등록한 판본을 소급 적용하지 않습니다.'
    return ''


def supports(topic, hit, query=''):
    official=hit.get('official') or {}; text=flat(hit['text']); title=flat(hit['title'])
    if official:
        expected=ARTICLE.get(topic)
        if not expected or official.get('title')!=expected[0] or not official.get('article','').startswith(expected[1]):return False
        if topic in SPECIAL and SPECIAL[topic] not in text:return False
        return True
    # A meeting memo is searchable reference material, not a rule establishing an entitlement.
    # Uploaded regulations/manuals still need a substantive rule in the matching passage.
    if any(t in title for t in ('합성','모의','시연')):return False
    if hit.get('kind') not in ('법령·규정','기관 지침','업무편람'):return False
    anchors=TOPICS[topic][1]
    if not any(a in text for a in anchors):return False
    if re.search(r'다루지않|기준.{0,10}(?:없|정하지않)|검토하지않|별도확인필요',text):return False
    if not re.search(r'하여야|해야|한다|정한다|할수있|신청|지급|제출',text):return False
    deadline=topic=='goods_payment_deadline' or topic=='travel_settlement' and any(t in flat(query) for t in ('기한','언제까지','며칠','몇일'))
    if deadline and not re.search(r'\d+(?:영업)?(?:일|주|개월)',text):return False
    if topic=='goods_inspection_limit' and not re.search(r'\d+[만천억,]*원',text):return False
    return True


def filter_hits(query,hits,plan):
    if plan['status']=='clarify':return [],plan['question']
    topics=plan['topics']
    question=supplement.clarification(query,topics,hits)
    if question:
        plan.update(status='clarify',question=question);return [],question
    if 'occasion' in topics and not supplement.occasion_supported(query):
        return [],'등록한 해당 신분의 경조사 별표에 없는 사유·관계입니다. 소속 기관의 복무 조례·지침을 추가 확인해야 합니다. 다른 관계의 휴가 일수를 대신 적용하지 않습니다.'
    required={(t,tuple(target)) for t in topics for target in (supplement.requirements(t,query) or [(None,None)])}
    candidates=[]
    for h in hits:
        covered={(t,target) for t,target in required if (supplement.matches(h,target) if target[0] else supports(t,h,query))}
        if covered:candidates.append((h,covered))
    candidates=[c for c in candidates if c[1]]
    needed=set(required);selected=[]
    while needed and candidates and len(selected)<6:
        candidates.sort(key=lambda c:(len(c[1]&needed),c[0]['score']),reverse=True)
        hit,covered=candidates.pop(0)
        if not covered&needed:break
        selected.append(hit);needed-=covered
    if needed:
        reasons=[MISSING.get(t,'등록 자료에서 '+TOPICS[t][0]+'의 직접 근거를 확인할 수 없습니다.') for t in sorted({t for t,_ in needed})]
        return [],' '.join(reasons)
    return selected,''


def summary_allowed(rule_id,query,plan):
    if not plan:return True
    topics=set(plan['topics']);q=flat(query)
    rules={
        'settlement': {'travel_settlement'}, 'additional-settlement': {'travel_extra'},
        'local-trip': {'travel_local'}, 'daily-car': {'travel_daily'}, 'annual-leave': {'annual'},
        'sick-leave': {'sick'}, 'health-leave': {'public_health'}, 'blood-leave': {'public_blood'},
        'childcare-time': {'childcare'}, 'family-care': {'family_care'},
        'goods-inspection': {'goods_inspection'}, 'goods-payment': {'goods_payment'},
        'card-points': {'account_points'}, 'instructor-disclosure': {'account_lecturer'},
    }
    if topics!=rules.get(rule_id,set()):return False
    if rule_id=='annual-leave':
        years=[int(n) for n in re.findall(r'(?<!\d)(\d{1,2})년',q)]
        return bool(years and len(years)==1 and years[0]>=6 and not any(t in q for t in ('보상','휴직','산입','병가','가산','22일')))
    if rule_id=='additional-settlement' and any(t in q for t in ('퍼센트','비율','%','식비','식대')):return False
    if rule_id=='goods-inspection' and any(t in q for t in ('비용','부담','파손','성능시험')):return False
    if rule_id=='sick-leave' and any(t in q for t in ('시간','환산')):return False
    if rule_id=='daily-car' and not any(t in q for t in ('공무용차량','공용차량','관용차량','공용차','관용차')):return False
    if rule_id=='family-care' and not any(t in q for t in ('유급','무급','급여','일수','며칠','몇일','열흘','10일')):return False
    if rule_id=='local-trip' and any(t in q for t in ('범위','거리','12킬로','12km','정의')):return False
    return True
