"""명시적으로 합성 표시한 고정 시연. 실제 계산기를 통과한 결과만 보고한다."""

FIXTURES={'out':('travel-sample-receipt.png','2026-10-15 08:14 코레일 52,300원 승인'),
          'hotel':('travel-demo-hotel.png','2026-10-15 20:41 가람호텔 88,000원 승인'),
          'back':('travel-demo-return.png','2026-10-17 17:20 코레일 52,300원 승인')}
SCENARIOS={
 'ordinary':dict(title='일반출장 · 계산·증빙 묶음',description='부산 회의출장 2박 3일. 운임·일비·식비·숙박비와 원본 3건을 확인합니다.',
                 purpose='회의 (합성 시연)',fixtures=['out','hotel','back'],expected=dict(total=342600,status='calculated_for_review',transactions=3,issues=0,lines=dict(transport=104600,daily=75000,meal=75000,lodging=88000)),
                 steps=['342,600원과 항목별 계산식 확인','근거 조문·보존 원문 펼치기','초안·ZIP에서 원본과 누락 목록 확인']),
 'training':dict(title='교육출장 · 합숙 기준',description='부산 합숙 교육 3일. 입교·수료일만 일비 지급, 숙식은 가상 교육기관 청구액을 적용합니다.',
                 purpose='교육 (합성 시연)',fixtures=['out','back'],expected=dict(total=221600,status='calculated_for_review',transactions=2,issues=0,lines=dict(transport=104600,daily=50000,meal=27000,lodging=40000)),
                 steps=['일비 50,000원과 합계 221,600원 확인','국가 교육훈련 별표 1 근거 확인','기관 청구액은 합성 입력이며 담당자 확인이 남는 점 확인']),
 'anomaly':dict(title='오류 탐지 · 보류 시연',description='동일 거래 중복·취소 연관·기간 외 거래·해석 실패를 섞어, 지급액을 확정하지 않는 흐름을 확인합니다.',
                 purpose='회의·오류 탐지 (합성 시연)',fixtures=[],expected=dict(total=None,status='blocked',transactions=4,issues=1,duplicates_skipped=1,cancellation=True,outside=True),
                 steps=['완전히 같은 입력 1건의 중복 등록 제외 확인','취소 연관·기간 외 거래와 해석 실패 확인','합계 대신 계산 보류·보완 작업 확인'])
}


def definition(key):
    import copy
    scenario=copy.deepcopy(SCENARIOS[key])
    scenario['trip']=dict(organization_id='national-general',work_pattern='일반근무',destination='부산',purpose=scenario['purpose'],
                          start_date='2026-10-15',end_date='2026-10-17',transport='철도',overnight=True,meals_provided=False)
    scenario['expected']['originals']=len(scenario['fixtures'])
    scenario['inputs']=dict(grade='group2',conditions_confirmed=True,ordinary_fare_confirmed=True)
    if key=='ordinary':
        scenario['inputs'].update(lodging_scope_confirmed=True,lodging_nights=[dict(night='2026-10-15',region='metropolitan'),dict(night='2026-10-16',region='metropolitan')])
    elif key=='training':
        scenario['inputs']['training']=dict(entry_date='2026-10-15',completion_date='2026-10-17',teaching_dates=['2026-10-15','2026-10-16','2026-10-17'],residential=True,dorm_available=True,
            institution_lodging=40000,institution_meal=27000,notice_reference='[합성] 교육운영과-DEMO-001 / 실제 청구 아님',notice_confirmed=True,costs_confirmed=True)
    else:
        scenario['inputs']['lodging_not_claimed']=True
    scenario['text']='\n'.join(FIXTURES[key][1] for key in scenario['fixtures']) if key!='anomaly' else '\n'.join([
        '2026-10-15 09:00 SRT 45,000원 승인','2026-10-15 09:00 SRT 45,000원 승인','2026-10-15 09:02 SRT 45,000원 승인',
        '2026-10-15 09:03 SRT 45,000원 취소','2026-10-18 13:21 가람카페 6,500원 승인','2026-10-15 99:99 가람호텔 금액미확인'])
    return scenario


def fixture_bytes(root,keys):
    result=[]
    for key in keys:
        raw=(root/'static'/FIXTURES[key][0]).read_bytes()
        if not raw.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Invalid synthetic PNG fixture')
        result.append((key,raw))
    return result


def report(view,expected):
    result=view['calculation']['result'] if view.get('calculation') else {}
    rows=view['review']['transactions'];checks=[]
    def add(key,title,want,actual): checks.append(dict(key=key,title=title,expected=want,actual=actual,passed=want==actual))
    add('total','검토용 산정액',expected['total'],result.get('estimated_total'))
    add('status','계산 상태',expected['status'],result.get('status'))
    add('transactions','등록 거래 수',expected['transactions'],len(rows))
    add('issues','남은 해석 실패 수',expected['issues'],len(view['parse_issues']))
    add('originals','보존한 합성 원본 수',expected['originals'],len(view.get('documents',[])))
    add('fresh','계산 이후 자료 변경 없음',True,bool(view.get('calculation') and not view['calculation']['stale']))
    if 'duplicates_skipped' in expected:
        add('duplicates','초기 중복 등록 제외 수',expected['duplicates_skipped'],expected.get('_initial_duplicates'))
    for key,amount in expected.get('lines',{}).items():
        add(key,{'transport':'운임','daily':'일비','meal':'식비','lodging':'숙박비'}[key],amount,next((r['amount'] for r in result.get('lines',[]) if r['key']==key),None))
    if 'cancellation' in expected:
        add('cancellation','취소 연관 경고',True,any(any('취소' in f for f in r['flags']) for r in rows))
        add('outside','기간 외 경고',True,any('출장기간 외 거래' in r['flags'] for r in rows))
        add('cancel_not_included','취소 거래 합산 차단',True,all(not r['included'] for r in rows if r['cancelled']))
    return dict(passed=all(r['passed'] for r in checks),checks=checks,
                notice='합성 시연자료의 기대값 비교입니다. 실제 지급·증빙 진위·기관 승인을 인증하지 않습니다.')
