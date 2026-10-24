"""교육기관 입교에 대한 제한된 교육훈련 여비. 일반출장 계산과 별도로 실행한다."""
from datetime import date, timedelta


def calculate_training(case, review, inputs, pack, block, line, result, errors, rates):
    t=inputs['training']; trip=case['trip_json']; profile=pack['profile']
    prefix=profile.get('training_prefix')
    if not prefix:
        block('TRAINING_SCOPE','이 저장 건의 규정팩에는 적용 가능한 교육훈련 계산 기준이 없습니다. 소방은 교육기관별 적용기준을 추가 확인해야 합니다. 기존 건은 자동으로 새 규정팩으로 바뀌지 않습니다.',['N8','M_TRAINING'])
        return result()
    refs=[prefix+'_TABLE',prefix+'_BODY']
    start=date.fromisoformat(trip['start_date']); end=date.fromisoformat(trip['end_date'])
    count=(end-start).days+1
    all_days={(start+timedelta(days=n)).isoformat() for n in range(count)}
    if trip['start_date'] < profile['training_from']:
        block('TRAINING_VERSION',f"이 교육훈련 기준은 {profile['training_from']} 이후 건에만 적용합니다. 이전 시행본을 확인하세요.",refs)
    if not t['notice_confirmed'] or not t['notice_reference']:
        block('TRAINING_NOTICE','교육기관 입교·수료·교육일정·합숙/기숙사 제공 가능 여부 및 청구 안내문 문서번호를 확인하세요.',refs)
    if not t['costs_confirmed']:
        block('TRAINING_COSTS','실제 비용 발생 여부, 무상 제공·기관 직접 지급·중복 지원 및 청구액의 근거를 확인하세요.',refs)
    if t['entry_date']!=trip['start_date'] or t['completion_date']!=trip['end_date'] or set(t['teaching_dates'])!=all_days or count>15:
        block('TRAINING_DAYS','이번 계산은 15일 이내, 여행 시작·종료일과 입교·수료일이 같고 매일 교육이 있는 과정입니다. 전후 이동·휴일 체재·휴강·장기과정은 별도 검토합니다.',refs)
    if t['dorm_available'] and not t['residential']:
        block('TRAINING_DORM','기숙사·합숙 이용이 가능하면 임의로 비합숙 기준을 적용할 수 없습니다. 합숙 기준 또는 기관 확인이 필요합니다.',refs)
    if inputs['additional_review'] or inputs['vehicle_dates'] or inputs['assigned_vehicle'] or trip['transport']=='관용차':
        block('TRAINING_SPECIAL','차량 이용·전용차량·기관 특례·외부 지원 등이 있는 교육훈련은 감액·지급 제한을 별도 확인합니다.',refs+['N28'])
    if t['settlement_method']!='actual':
        block('TRAINING_FIXED','정액 운임·숙박 지급은 별도의 정액여비 지급기준 검토가 필요합니다. 현재는 기관이 허용한 실비정산 방식을 지원합니다.',refs)
    rows=review['transactions']; included=[r for r in rows if r['included']]
    if case['parse_issues'] or any(r['decision']=='pending' for r in rows):
        block('UNRESOLVED','해석실패·보류 거래를 먼저 검토하세요.',['N8'])
    if any(r['flags'] for r in included):
        block('FLAGGED_TRANSACTION','포함 거래의 기간 외·중복·용도 경고를 먼저 해결하세요.',['N8'])
    if any(r['category'] not in ('transport','lodging') for r in included):
        block('TRAINING_DUPLICATE','음식점·기타 거래를 여비와 중복 합산하지 않습니다. 교육기관 식비 청구액은 안내문 근거로 별도 입력하세요.',refs)
    fare=sum(r['amount'] for r in included if r['category']=='transport')
    lodging=sum(r['amount'] for r in included if r['category']=='lodging')
    outside=inputs['travel_scope']=='outside'; residential=t['residential']; zero=set(t['zero_items'])
    if outside and 'transport' not in zero:
        if trip['transport'] not in ('철도','버스') or not inputs['ordinary_fare_confirmed'] or not fare:
            block('TRAINING_FARE','실비정산 방식의 일반실 철도·버스 운임과 포함 거래를 확인하세요. 미발생·미청구 항목은 아래에서 선택합니다.',refs+['N10','N13'])
    if (not outside or 'transport' in zero) and fare:
        block('TRAINING_FARE_ZERO','근무지내 교육 또는 운임 미발생·미청구 선택과 포함한 운임 거래가 충돌합니다.',refs)
    # 제1호 교육은 위에서 보류하므로 구조 확인에는 제2호 기준을 사용한다.
    if rates['lodging_caps'] is None:
        from .travel_rates import checked_table, group_rates
        rates=group_rates(pack,'group2',checked_table(pack))
    nights=inputs['lodging_nights']; cap=sum(rates['lodging_caps'][n['region']] for n in nights)
    if any(not trip['start_date']<=n['night']<trip['end_date'] for n in nights):
        block('NIGHT_RANGE','숙박일이 교육기간을 벗어납니다.',['N16_4'])
    if not trip['overnight'] and (nights or lodging or t['institution_lodging']):
        block('NIGHT_MISMATCH','숙박 없음과 숙박 청구가 충돌합니다.',['N16_4'])
    if 'lodging' in zero and (lodging or nights or t['institution_lodging']):
        block('TRAINING_LODGING_ZERO','숙박 미발생·미청구 항목에 숙박 청구액·거래·숙박일이 있습니다.',refs)
    if inputs['lodging_not_claimed'] and 'lodging' not in zero:
        block('TRAINING_ZERO_INPUT','숙박비 미청구는 교육훈련 미발생·미청구 항목에서도 선택하세요.',refs)
    if residential:
        if lodging or nights:
            block('TRAINING_INSTITUTION','합숙 숙박비는 교육기관 청구액을 사용합니다. 호텔 거래·일반 숙박일을 합산하지 않습니다.',refs)
        lodging_amount=t['institution_lodging']; meal=t['institution_meal']
        if t['lunch_deduction']:
            block('TRAINING_MEAL_INPUT','합숙 식비에는 교육기관 청구액/구내식당 가격을 입력하고 비합숙 중식 차감액은 비워 주세요.',refs)
    else:
        if t['institution_lodging']:
            block('TRAINING_INSTITUTION','비합숙 실비 숙박은 영수증 거래와 실제 숙박일을 사용하세요.',refs)
        lodging_amount=min(lodging,cap) if outside else 0
        if outside:
            if t['institution_meal']:
                block('TRAINING_MEAL_INPUT','근무지외 비합숙은 정액 식비에서 교육기관 중식 청구액을 차감합니다. 합숙 식비 입력은 비워 주세요.',refs)
            meal=rates['meal_daily']*count-t['lunch_deduction']
            if meal<0 or ('meal' in zero and t['lunch_deduction']):
                block('TRAINING_MEAL_LIMIT','중식 차감액이 식비 한도를 넘거나 식비 미발생 선택과 충돌합니다.',refs)
            if trip['meals_provided'] and (not t['lunch_deduction'] or not t.get('lunch_only_provided')) and 'meal' not in zero:
                block('TRAINING_MEALS_PROVIDED','제공 식사의 내역·부담 주체를 확인하세요. 교육기관 중식 청구액 차감 외의 제공식사는 별도 검토하거나 식비 미청구로 처리합니다.',refs)
        else:
            meal=t['institution_meal']
            if not meal and 'meal' not in zero:
                block('TRAINING_LOCAL_MEAL','근무지내 비합숙은 교육기관 청구 식비 방식을 지원합니다. 식비 3분의 1 정액 방식은 끝수 처리 기준을 별도 확인하세요.',refs)
            if t['lunch_deduction']:
                block('TRAINING_MEAL_INPUT','근무지내 비합숙은 기관 청구 식비를 사용하며 중식 차감액은 비워 주세요.',refs)
        if not outside and (lodging or nights):
            block('TRAINING_LOCAL_LODGING','근무지내 비합숙 교육은 숙박비를 지급하지 않습니다.',refs)
        if outside and trip['overnight'] and 'lodging' not in zero and (not nights or not lodging or not inputs['lodging_scope_confirmed']):
            block('LODGING_DETAILS','비합숙 실비정산은 숙박 거래·지역별 실제 숙박일·청구 범위를 확인하세요.',refs+['N16_4'])
    if 'meal' in zero and t['institution_meal']:
        block('TRAINING_MEAL_ZERO','식비 미발생·미청구와 교육기관 식비 청구액이 충돌합니다.',refs)
    if errors: return result()
    boundary=len({t['entry_date'],t['completion_date']}); others=len(t['teaching_dates'])-boundary
    unit=rates['daily']; other_unit=0 if residential else unit//2
    daily=unit*boundary+other_unit*others
    line('transport','교육훈련 운임',fare if outside and 'transport' not in zero else 0,'근무지외 일반실 철도·버스 포함 실비' if outside else '근무지내 교육 → 운임 미지급',refs,{'transaction_ids':[r['id'] for r in included if r['category']=='transport']})
    line('daily','교육훈련 일비',0 if 'daily' in zero else daily,f"입교·수료 {boundary}일 × {unit:,}원 + 기타 교육일 {others}일 × {other_unit:,}원"+(' · 미발생·미청구 0원' if 'daily' in zero else ''),refs+[rates['clause_id']])
    line('meal','교육훈련 식비',0 if 'meal' in zero else meal,(f"교육기관 청구액/구내식당 가격 {t['institution_meal']:,}원" if residential or not outside else f"{rates['meal_daily']:,}원 × {count}일 - 교육기관 중식 청구액 {t['lunch_deduction']:,}원")+(' · 미발생·미청구 0원' if 'meal' in zero else ''),refs+([rates['clause_id']] if not residential and outside else []),{'notice_reference':t['notice_reference']})
    line('lodging','교육훈련 숙박비',0 if 'lodging' in zero else lodging_amount,f"교육기관 청구액 {lodging_amount:,}원" if residential else f"min(숙박 실비 {lodging:,}원, 지역별 상한 합계 {cap:,}원)" if outside else '근무지내 비합숙 → 숙박 미지급',refs+(['M_LODGING','T2'] if not residential and outside else []),{'notice_reference':t['notice_reference'],'over_cap':max(0,lodging-cap) if not residential and outside else 0})
    out=result()
    out['warnings']=['교육기관 안내문·청구액은 사용자 확인 입력입니다. 등록금·교재대 등 교육훈련비는 여비에 합산하지 않습니다.','직접 지급·무상 제공·미발생 비용은 미청구 처리해야 합니다. 문자·영수증 진위와 최종 지급은 기관에서 확인하세요.']
    out['training_summary']={'residential':residential,'entry_date':t['entry_date'],'completion_date':t['completion_date'],'boundary_days':boundary,'other_teaching_days':others,'notice_reference':t['notice_reference']}
    return out
