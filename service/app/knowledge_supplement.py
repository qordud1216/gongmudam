"""Reviewed source requirements for newly collected tables and delegated contract rules."""
import re

TRAVEL='공무원 여비 규정'
LOCAL='지방공무원 복무규정'
NATIONAL='국가공무원 복무규정'
LAW='지방자치단체를 당사자로 하는 계약에 관한 법률'
DECREE=LAW+' 시행령'


def flat(text):return re.sub(r'\s+','',text)


def national(query):return any(t in flat(query) for t in ('국가공무원','국가직','국가기관','중앙부처','소방공무원'))


def local(query):return any(t in flat(query) for t in ('지방공무원','지방직','지자체공무원'))


def foreign_query(query):
    q=flat(query)
    return any(t in q for t in ('국외','해외','외국','미국','일본','중국','도쿄','뉴욕','런던','파리','홍콩','싱가포르','제네바','워싱턴','로스엔젤레스','샌프란시스코','모스크바','가등급','나등급','다등급','라등급'))


def requirements(topic,query):
    if topic=='goods_payment_interest' and not any(t in flat(query) for t in ('계산','산식','이율','연체이자율','얼마')):return None
    return {
        'travel_rate_domestic':[(TRAVEL,'별표 2 '),(TRAVEL,'제16조(')],
        'travel_rate_foreign':[(TRAVEL,'별표 4 '),(TRAVEL,'제16조(')],
        'travel_group':[(TRAVEL,'별표 1 ')],
        'travel_private_car':[(TRAVEL,'별표 2 ')],
        'goods_inspection_limit':[(LAW,'제17조('),(DECREE,'제65조(')],
        'goods_inspection_deadline':[(DECREE,'제64조(')],
        'goods_payment_deadline':[(LAW,'제18조('),(DECREE,'제67조(')],
        'goods_payment_interest':[(LAW,'제18조('),(DECREE,'제68조(')],
        'goods_quote':[(DECREE,'제30조(')],
        'occasion':[(NATIONAL,'별표 2 '),(NATIONAL,'제20조(')] if national(query) else [(LOCAL,'별표 1 '),(LOCAL,'제7조의7(')],
    }.get(topic)


def matches(hit,target):
    official=hit.get('official') or {}
    return official.get('title')==target[0] and official.get('article','').startswith(target[1])


def occasion_supported(query):
    event=occasion_event(query)
    if event=='unsupported':return False
    # The national table includes additional relatives; the local decree's table
    # lists only siblings. Other local occasions require the institution's ordinance.
    return not event or not event.startswith('death-') or national(query) or event=='death-sibling'


def occasion_event(query):
    q=flat(query)
    if '결혼' in q:
        if any(t in q for t in ('형제','자매','손자','손녀','부모','사촌','조카','며느리','사위')):return 'unsupported'
        if any(t in q for t in ('자녀','아들','딸')):return 'marriage-child'
        if any(t in q for t in ('본인','내결혼','제가결혼','나결혼')):return 'marriage-self'
        return None
    if '출산' in q:return 'birth' if any(t in q for t in ('배우자','아내','와이프')) else None
    if '입양' in q:return 'adoption' if '본인' in q else None
    if any(t in q for t in ('사망','돌아가셨','돌아가신','부친상','모친상','장례')):
        if any(t in q for t in ('손자','손녀','사촌','조카','삼촌','이모','고모','형수','매형','제수','형부')) or re.search(r'(?:형제(?:자매)?|자매)(?:의)?배우자',q):return 'unsupported'
        if any(t in q for t in ('조부모','외조부모','할아버지','할머니')):return 'death-grandparent'
        if any(t in q for t in ('부모','아버지','어머니','부친상','모친상')):return 'death-parent'
        if any(t in q for t in ('형제','자매')):return 'death-sibling'
        if '자녀' in q:return 'death-child'
        if '배우자' in q:return 'death-spouse'
    return None


def foreign_grade(query):
    q=flat(query);m=re.search(r'([가나다라])등급',q)
    if m:return m[1]
    if any(t in q for t in ('도쿄','뉴욕','런던','파리','홍콩','싱가포르','제네바','워싱턴','로스엔젤레스','샌프란시스코','모스크바')):return '가'
    return None


def grade_conflict(query):
    q=flat(query);explicit=re.findall(r'([가나다라])등급',q)
    without_grade=re.sub(r'[가나다라]등급','',q)
    return bool(explicit and foreign_grade(without_grade)=='가' and any(g!='가' for g in explicit))


def clarification(query,topics,hits):
    q=flat(query)
    if 'occasion' in topics and not (national(query) or local(query)):
        if any((h.get('official') or {}).get('collection')=='v40' for h in hits):
            return '국가공무원·지방공무원 등 적용 신분과 경조사 대상(본인·자녀·배우자 등)을 알려주세요. 별표와 기관 조례가 다를 수 있어요.'
    if 'occasion' in topics and not occasion_event(query) and '표' not in q:
        if any((h.get('official') or {}).get('collection')=='v40' for h in hits):return '어떤 경조사이며 누구에 관한 사유인가요? 본인·자녀 결혼, 배우자 출산, 사망한 분과의 관계를 알려주세요.'
    if 'travel_rate_foreign' in topics:
        if any(matches(h,(TRAVEL,'별표 4 ')) for h in hits) and not ('지급표' in q or '금액표' in q or '표전체' in q):
            if grade_conflict(query):return '출장 도시와 입력한 등급이 서로 맞는지 확인해야 해요. 등록 별표의 도시별 등급을 확인한 뒤 출장 도시·등급을 다시 알려주세요.'
            group=bool(re.search(r'제?2호|제?1호[가나다라]목',q))
            grade=bool(foreign_grade(query))
            if not(group and grade):return '국외 여비는 지급 구분과 국가·도시 등급에 따라 달라요. 별표 1의 지급 구분(예: 제2호)과 출장 도시 또는 등급을 알려주세요. 금액은 미 달러화 기준이에요.'
    return ''


# These rates and paraphrases were checked against the complete PDF pages and
# decree paragraphs. A different digest must receive a new review before reuse.
REVIEWED={
 'travel.html':'0b22c01ecffbd69f3c7ceecb499322d0f3d05a21ac9928188fc97d101bb29983',
 'goods_inspection.html':'0fdad6efb955a58d108c6c7333904de037dc928df82a45c9a95bbdc148c4b472',
 'travel_annex2.pdf':'3df802c01e9114aeebe7121d9a4efc2f58f607daa11120cf97028589e928c516',
 'travel_annex4.pdf':'6ab17850ee25dc9cf12e79ec2529e5260deb66687eea42b8426ce04123422f13',
 'leave_annex1.pdf':'38d5095d2162c76f63f1313a5d239ddd51a2cf35bfc09dc9592a77436be6f9b1',
 'national_leave_annex2.pdf':'d0729ac9f46986b5f2c1d0c3b58fe4913449276030f9240026935d686c4135d4',
 'goods_decree_30.html':'2295149b4f876d96b8378e1683281ef7780ad9671b752ae28145be3fdd22e0bb',
 'goods_decree_64.html':'327e6cf235be7813eaaa77dd61d34c07bae0700d95c4af50eb3fdb0932e36cda',
 'goods_decree_65.html':'b6fc611a79e7e9480449de9898799664f8f03611e8f99c4f9acd7069d3f5d5be',
 'goods_decree_67.html':'54c66cb1200baea79cc94dc70bef3585e58589cc82dbc95bde5537c5918a7a1a',
}


def summary(query,reply):
    from . import official_sources
    plan=reply.get('intent') or {};topics=plan.get('topics',[]);evidence=reply.get('evidence',[]);q=flat(query)
    if len(topics)!=1:return None
    topic=topics[0];nodes=[];title='';rule_id='extended-'+topic
    def item(target,text,*quotes):
        for i,h in enumerate(evidence,1):
            o=h.get('official') or {}
            if not matches(h,target) or not official_sources.metadata(h.get('sha256')):continue
            if REVIEWED.get(o.get('raw_file'))!=h.get('sha256'):continue
            if all(v in h['text'] for v in quotes):nodes.append(dict(text=text,ref=i,support_quotes=list(quotes)));return
        raise ValueError('Unreviewed or incomplete supporting context')
    try:
        if topic=='travel_rate_domestic':
            target=(TRAVEL,'별표 2 ');title='국내 여비는 지급 구분과 출장 지역을 함께 확인해요'
            item(target,'표의 일비와 식비는 각각 1일 25,000원이에요. 대통령·국무총리는 비고의 실비 예외를 확인해요.','25,000','대통령과','실비')
            item(target,'제2호 숙박비는 실비이며 1박 상한은 서울 100,000원, 광역시 80,000원, 그 밖의 지역 70,000원이에요.','제2호','100,000','80,000','70,000')
            item(target,'제1호 숙박비는 실비로 표시돼요. 제2호 상한을 모든 직급에 적용하지 않아요.','제1호','실비')
            item((TRAVEL,'제16조('),'공무용 차량을 이용하는 경우 등에는 일비를 2분의 1로 지급해요. 표의 금액과 실제 지급액을 구분해요.','일비의 2분의 1')
            item(target,'통합특별시는 종전 시·군·광역시 기준을 확인하고, 할인이 가능하면 할인 요금을 적용해요.','통합특별시는','할인된')
        elif topic=='travel_rate_foreign' and re.search(r'제?2호',q) and not re.search(r'제?1호',q) and len(set(re.findall(r'([가나다라])등급',q)))<=1 and foreign_grade(query):
            grade=foreign_grade(query);lodging,meal={'가':(176,81),'나':(137,59),'다':(106,44),'라':(81,37)}[grade]
            target=(TRAVEL,'별표 4 ');title=f'제2호 · {grade}등급의 국외 여비 기준이에요'
            item(target,f'일비 30달러, 숙박비는 실비로 상한 {lodging}달러, 식비 {meal}달러예요. 원화 금액이 아니에요.','미  달러화','제2호',str(lodging),str(meal))
            item(target,'지급 구분과 국가·도시 등급을 함께 확인해요. 도시가 따로 지정되어 있으면 국가의 일반 등급과 구분해요.','국가 및 도시별','도쿄')
            item(target,'숙박비 할인정액 지급은 별도 기준을 확인해요. 상한액을 무조건 정액 지급하는 방식으로 계산하지 않아요.','할인정액','실비')
        elif topic=='goods_inspection_limit':
            title='검사조서 작성 생략과 검사 자체를 구분해요'
            item((DECREE,'제65조('),'시행령에서 정한 기준 금액은 계약금액 3천만원이에요.','계약금액 3천만원')
            item((LAW,'제17조('),'금액에 따른 검사조서 작성 생략은 3천만원 미만 기준이에요. 정확히 3천만원인 계약은 금액 조건만으로 생략할 수 없어요.','대통령령으로 정하는 금액 미만의 계약')
            item((LAW,'제17조('),'검사 자체의 생략은 품질인증 물품 등 별도 요건이에요. 조서 작성 생략과 같은 뜻으로 처리하지 않아요.','품질인증','검사를 하지 아니할 수 있다')
        elif topic=='goods_payment_deadline':
            target=(DECREE,'제67조(');title='검사 완료와 청구일을 확인한 뒤 지급기한을 봐요'
            item(target,'원칙은 검사 완료 후 청구받은 날부터 5일 이내예요. 토요일과 공휴일은 제외해요.','검사를 완료한 후','5일','공휴일과 토요일은 제외')
            item(target,'행정안전부장관이 고시한 기간에는 3일 기준이 있어요. 현재 적용 여부는 해당 고시를 별도로 확인해야 해요.','행정안전부장관이 기간을 정하여 고시한 경우','3일')
            item(target,'합의한 특약은 5일을 초과하지 않는 범위에서 연장할 수 있고, 부당 청구 반송 후 재청구까지는 산입하지 않아요.','5일을 초과하지 않는 범위','반송한 날부터 재청구를 받은 날까지')
        elif topic=='goods_inspection_deadline':
            target=(DECREE,'제64조(');title='납품 완료 통지를 받은 날부터 검사기간을 확인해요'
            item(target,'원칙은 이행 완료 통지를 받은 날부터 14일 이내예요. 고시한 특례기간에는 7일 기준이 있어요.','통지받은 날부터 14일','7일')
            item(target,'정해진 연장 사유, 불가항력, 시정 완료 후 기산 기준도 함께 확인해요.','그 사유가 소멸된 날부터 3일','시정을 완료한 사실')
        elif topic=='goods_quote':
            target=(DECREE,'제30조(');title='견적서는 2인 이상 원칙과 1인 예외를 함께 봐요'
            item(target,'수의계약은 2인 이상 견적이 원칙이에요. 추정가격 2천만원 이하 물품 제조·구매 등에는 1인 견적 예외가 있어요.','2인 이상','추정가격이 2천만원 이하','1인')
            item(target,'일부 기업·조합은 5천만원 이하 예외가 있지만 기업 유형과 고용비율 등 요건을 확인해야 해요. 계약금액과 추정가격도 구분해요.','추정가격이 5천만원 이하','고용비율')
        elif topic=='occasion':
            target=(NATIONAL,'별표 2 ') if national(query) else (LOCAL,'별표 1 ')
            label='국가공무원' if national(query) else '지방공무원';title=label+' 경조사 별표에서 확인해요'
            event=occasion_event(query)
            if event in ('marriage-self','marriage-child'):
                child=event=='marriage-child'
                item(target,('자녀 결혼은 1일이에요.' if child else '본인 결혼은 5일이에요.'),'결혼','자녀' if child else '본인')
            elif event=='birth':
                item(target,'배우자 출산은 20일이며, 한 번에 둘 이상의 자녀를 출산하면 25일이에요.','배우자','20일','25일')
            elif event=='adoption':item(target,'본인 입양은 20일이며, 비고에서 정한 입양의 범위를 확인해요.','입양','20')
            elif event and event.startswith('death-'):
                text={'death-sibling':'본인 및 배우자의 형제자매 사망은 3일이에요.',
                      'death-grandparent':'본인 및 배우자의 조부모·외조부모 사망은 3일이에요.',
                      'death-parent':'본인 및 배우자의 부모 사망은 5일이에요.',
                      'death-child':'자녀와 그 자녀의 배우자 사망은 3일이에요.',
                      'death-spouse':'배우자 사망은 5일이에요.'}[event]
                item(target,text,'사망')
            else:return None
            item(target,'원격지의 왕복 소요일수와 입양 범위는 비고를 함께 확인해요. 구체적인 사용기한·분할은 별도 복무지침을 확인해요.','원격지','입양')
            if not national(query):item(target,'별표에 없는 경조사 사유는 소속 기관의 조례를 별도로 확인해요.','경조사')
        else:return None
    except ValueError:return None
    if not nodes:return None
    return dict(kind='summary',title=title,rule_id=rule_id,
        reviewed_source_sha256s=sorted({evidence[n['ref']-1]['sha256'] for n in nodes}),
        branches=[dict(label='질문에 맞는 기준',items=nodes)],
        note='등록한 현행 원문과 비고를 확인한 요약이에요. 기관별 조례·지침과 실제 적용 조건은 근거에서 함께 확인하세요.')
