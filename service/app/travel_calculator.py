"""출처 확인한 제한 범위의 결정적 여비 산정. 불명확한 조건은 합계를 반환하지 않는다."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from . import travel_rates,travel_validity,regulation_registry

BUNDLE_PATH=Path(__file__).parent/'rulepacks'/'domestic_reviewed_2026_10.json'


def load_bundle():
    raw=BUNDLE_PATH.read_bytes()
    base_sha=hashlib.sha256(raw).hexdigest()
    active=regulation_registry.active_bundle(base_sha)
    bundle=active or json.loads(raw)
    bundle['bundle_sha256']=regulation_registry.sha(regulation_registry.dumps(bundle).encode()) if active else base_sha
    return bundle


def select_pack(organization_id):
    bundle=load_bundle()
    profile=bundle['profiles'].get(organization_id)
    return {**bundle,'profile':profile} if profile else None


def preserved_sources():
    """보존한 과거 배포본의 원문도 주소·해시로 조회한다."""
    sources={}
    for path in sorted(BUNDLE_PATH.parent.glob('domestic*.json')):
        for key,source in json.loads(path.read_text(encoding='utf-8')).get('sources',{}).items():
            sources[(key,source['sha256'])]=source
    for key,source in load_bundle()['sources'].items():
        sources[(key,source['sha256'])]=source
    return sources


def basis(pack, ids):
    found=[]
    for key in dict.fromkeys(ids+pack['profile']['scope_basis']):
        clause=copy.deepcopy(pack['clauses'][key])
        source=pack['sources'][clause['source_id']]
        found.append({**clause,'document':source['title'],'source_version':source['version'],
                      'effective_date':source['effective_date'],'verified_on':source['verified_on'],
                      'url':source['url'],'source_sha256':source['sha256'],
                      'registered_excerpt_sha256':source.get('excerpt_sha256'),
                      'original_url':source.get('original_url',source['url']),
                      'download_url':'/api/travel/legal-sources/'+clause['source_id']+'?sha256='+source['sha256']})
    return found


def searchable_rules(pack):
    """검증 범위 내의 공식 출처 설명. 직접 전사한 원문이 아닌 검토한 요약임을 명시한다."""
    result=[]
    allowed=pack['profile']['source_ids']
    for key,clause in pack['clauses'].items():
        if clause['source_id'] not in allowed:
            continue
        src=pack['sources'][clause['source_id']]
        result.append({'id':f"{pack['version']}:{key}",'pack_id':pack['profile']['id'],
                       'title':src['title'],'article':clause['article'],'text':clause['summary'],
                       'effective_date':src['effective_date'],'expiry_date':None,'version':src['version'],
                       'status':'source_verified','source_url':src['url'],'verified_on':src['verified_on'],
                       'source_sha256':src['sha256'],'content_kind':'reviewed_summary'})
    return result


def calculate(case, review, inputs, pack):
    trip=case['trip_json']
    errors=[]
    lines=[]
    def block(code,message,refs):
        errors.append({'code':code,'message':message,'basis':basis(pack,refs) if pack else []})
    def line(key,label,amount,formula,refs,details=None):
        lines.append({'key':key,'label':label,'amount':amount,'formula':formula,
                      'basis':basis(pack,refs),'details':details or {}})
    base={'engine_version':pack['engine_version'] if pack else 'domestic-1.0',
          'rulepack_id':pack['profile']['id'] if pack else None,
          'rulepack_version':pack['version'] if pack else None,
          'bundle_sha256':pack['bundle_sha256'] if pack else None,
          'inputs':inputs,'payable_amount':None,
          'notice':'규정 기준 검토용 산정액입니다. 증빙 진위·기관 승인·최종 지급을 확정하지 않습니다.'}
    def result():
        return {**base,'status':'blocked' if errors else 'calculated_for_review',
                'estimated_total':None if errors else sum(x['amount'] for x in lines),
                'lines':lines if not errors else [],'blockers':errors,
                'warnings':['문자·영수증 텍스트는 진위 미검증입니다. 공식 증빙과 기관 결재를 확인하세요.',
                            '제공 식사·기관별 추가 감액·특례가 있으면 일반식으로 확정하지 않습니다.']}
    if not pack:
        block('NO_LEGAL_PACK','이 기관은 검증된 계산 규정팩이 없습니다. 기관명·지역·직군만으로 다른 기관 기준을 자동 적용하지 않습니다.',[])
        return result()
    holds=regulation_registry.holds(pack,trip)
    if holds:
        base['regulatory_hold']=holds
        block('REGULATION_CHANGED',holds[0]['message'],['N7'])
        return result()
    if case.get('unconfirmed_documents'):
        block('DOCUMENT_UNCONFIRMED','원본과 추출 후보를 확인하지 않은 첨부파일이 있습니다. 거래 반영 또는 사유 있는 제외를 먼저 완료하세요.',['N8'])
    start=date.fromisoformat(trip['start_date']); end=date.fromisoformat(trip['end_date'])
    days=(end-start).days+1
    temporal=travel_validity.assess(pack,start,end)
    base['temporal']=temporal
    if not temporal['allowed']:
        block('VERSION_RANGE',temporal['message'],['N7'])
    elif temporal['is_estimate']:
        base['notice']=temporal['message']+' 금액은 지급 확정액이 아닙니다.'
    if not inputs['conditions_confirmed']:
        block('CONDITIONS','출장명령·실제 공무 여행일수·기관 추가 감액·예외 여부를 확인해 주세요.',['N5','N28'])
    table=None
    try:
        table=travel_rates.checked_table(pack)
        # 새 금액표 계산에서 사용한 법령·지침·기관 조례 원본도 함께 대조한다.
        if table is not None:
            source_ids=['national','guide']+[pack['clauses'][key]['source_id'] for key in pack['profile']['scope_basis']]
            if inputs.get('training') and pack['profile'].get('training_prefix'):
                source_ids += [pack['clauses'][pack['profile']['training_prefix']+suffix]['source_id'] for suffix in ('_TABLE','_BODY')]
            travel_rates.verify_sources(pack,source_ids)
    except travel_rates.RateTableError as exc:
        block('RATE_SOURCE',str(exc),['N3','T2'])
        return result()
    if inputs.get('journey_area','domestic')!='domestic':
        block('OVERSEAS','이 정산 계산은 국내출장용입니다. 국외는 별표 4의 국가·도시 등급, 지급 세부구분·환율·체재 조건을 확인한 별도 계산이 필요합니다.',['N16_1'])
    rates=travel_rates.group_rates(pack,inputs['grade'],table)
    if rates is None or (inputs['grade']=='group1' and (inputs.get('training') or
            (inputs['travel_scope']=='outside' and not inputs.get('group1_standard_confirmed')))):
        block('GRADE','별표 1 지급 구분을 확인하세요. 제1호 일반출장은 대통령·국무총리의 일비·식비 실비 예외 대상이 아님을 추가 확인해야 합니다. 제1호 교육훈련과 기존 제2호 전용 규정팩은 별도 검토합니다.',['N3','T2'])
    if rates is None:
        rates=travel_rates.group_rates(pack,'group2',table)
    if table is not None and inputs['grade'] in table['groups'] and (inputs['travel_scope']=='outside' or inputs.get('training')):
        base['rate_snapshot']={'currency':table['currency'],'grade':inputs['grade'],
            'group':copy.deepcopy(rates),'table_sha256':pack['domestic_table_sha256'],
            'source_excerpt_sha256':copy.deepcopy(table['source_excerpt_sha256']),
            'checked_on':table['checked_on'],'basis':basis(pack,['T1',rates['clause_id']])}
    if inputs.get('training'):
        from .travel_training import calculate_training
        return calculate_training(case,review,inputs,pack,block,line,result,errors,rates)
    if any(word in trip['purpose'] for word in ['교육','훈련','연수']):
        block('TRAINING','교육·훈련·연수는 교육대상·합숙·입교·수료일 등의 별도 기준을 검토해야 합니다. 일반출장 합계를 적용하지 않습니다.',['N8','M_TRAINING'])
    if inputs['additional_review']:
        block('SPECIAL','외부 지원·상급자 동행·기관 특례·추가 감액 등은 담당자 검토 후 별도 계산이 필요합니다.',['N28'])
    vehicles=inputs['vehicle_dates']
    if any(not trip['start_date']<=d<=trip['end_date'] for d in vehicles):
        block('VEHICLE_DATES','차량 이용일이 출장기간을 벗어납니다.',['N16_3','M_VEHICLE'])
    if inputs['travel_scope']=='inside':
        if days!=1 or trip['overnight']:
            block('LOCAL_DAYS','근무지내 계산은 당일·숙박 없는 출장 1건만 지원합니다.',['N18','M_NEAR'])
        if inputs['within_minutes'] is None or inputs['round_trip_km'] is None:
            block('LOCAL_INPUT','근무지내 해당 여부를 확인하고 출장시간·왕복거리를 입력하세요.',['N18','M_NEAR'])
        elif Decimal(str(inputs['round_trip_km']))<=Decimal('2'):
            block('NEAR','왕복 2km 이내는 정액이 아닌 실비 검토가 필요합니다. 근거리 실비는 이번 계산 범위에서 보류합니다.',['N18','M_NEAR']+(['G_NEAR'] if pack['profile']['id'].startswith('GYEONGGI') else []))
        if review['transactions'] and any(r['decision']=='pending' for r in review['transactions']):
            block('PENDING','보류 거래를 검토하세요. 근무지내 정액과 거래 실비를 중복 합산하지 않습니다.',['N18'])
        if not errors:
            rates=pack['rates']; minutes=inputs['within_minutes']
            amount=rates['within_4plus'] if minutes>=240 else rates['within_under4']
            deduction=rates['within_vehicle_deduction'] if vehicles or trip['transport']=='관용차' else 0
            final=0 if inputs['assigned_vehicle'] else max(0,amount-deduction)
            formula=f"{minutes}분 → {amount:,}원 - 차량감액 {deduction:,}원"
            if inputs['assigned_vehicle']: formula='전용차량 배정자 → 0원'
            line('within','근무지내 출장여비',final,formula,['N18','M_NEAR'],
                 {'minutes':minutes,'base_amount':amount,'vehicle_deduction':deduction,'assigned_vehicle':inputs['assigned_vehicle']})
        return result()
    # 근무지외 일반출장. 불확실한 경우 부분합계를 최종액처럼 노출하지 않는다.
    if days>15:
        block('LONG_STAY','15일을 넘는 출장은 도착일·체재일·타 지역 출장과 기관 예외를 추가 확인해야 합니다.',['N17'])
    if trip['meals_provided']:
        block('MEALS_PROVIDED','식사 제공이 있습니다. 실제 제공 내역과 기관 감액 기준 검토가 필요하여 식비를 임의로 3분의 1씩 공제하지 않습니다.',['N28','N16_5'])
    if inputs['assigned_vehicle']:
        block('ASSIGNED_VEHICLE','전용차량 배정자의 근무지외 지급 조건은 별도 검토가 필요합니다. 일반 공용차량 이용일만으로 확정하지 않습니다.',['N16_3','N28'])
    if trip['transport'] not in ('철도','버스','관용차'):
        block('TRANSPORT_MODE','현재 지급 구분에 맞는 철도·버스·공무용차량을 지원합니다. 항공·자가용·기타는 해당 예외와 세부기준 확인이 필요합니다.',['N12','N13','N15'])
    if trip['transport']=='관용차' and not vehicles:
        block('VEHICLE_MISSING','공무용차량을 사용한 실제 여행일을 입력해야 일비 감액을 계산할 수 있습니다.',['N16_3','M_VEHICLE'])
    if trip['transport'] in ('철도','버스') and not inputs['ordinary_fare_confirmed']:
        block('FARE_CLASS',f"일반 경로·지급 구분에 맞는 철도 등급({rates['rail_class']})·할인 적용 실비 여부를 확인해 주세요.",['N10','N13',rates['clause_id']])
    rows=review['transactions']
    if case['parse_issues'] or any(r['decision']=='pending' for r in rows):
        block('UNRESOLVED','보류 거래·해석실패가 남아 있습니다. 먼저 확인해 주세요.',['N8'])
    included=[r for r in rows if r['included']]
    if any(r['flags'] for r in included):
        block('FLAGGED_TRANSACTION','포함한 거래에 기간 외·유사 중복·용도 확인 경고가 있습니다. 거래를 정정하거나 제외해 주세요.',['N5','N8'])
    if any(r['category'] not in ('transport','lodging') for r in included):
        block('CATEGORY','식비는 정액 산정합니다. 음식점·기타 거래를 운임·숙박 실비와 중복 합산하지 않습니다.',['N16_5','T2'])
    transport=sum(r['amount'] for r in included if r['category']=='transport')
    lodging=sum(r['amount'] for r in included if r['category']=='lodging')
    if trip['transport']=='관용차' and transport:
        block('OFFICIAL_FARE','공무용차량 여행에 포함한 운임 거래가 있습니다. 운임 지급제한을 확인해 제외하세요.',['N15'])
    if trip['transport'] in ('철도','버스') and not transport:
        block('MISSING_FARE','해당 이동수단의 포함된 운임 거래가 없습니다. 다른 기관 부담·미청구 등은 별도 검토하세요.',['N8','N10'])
    nights=inputs['lodging_nights']
    if any(not trip['start_date']<=n['night']<trip['end_date'] for n in nights):
        block('NIGHT_RANGE','숙박일은 시작일부터 종료일 전날까지여야 합니다.',['N16_4'])
    if not trip['overnight'] and (nights or lodging):
        block('NIGHT_MISMATCH','숙박 없음으로 입력한 출장에 숙박일·숙박 거래가 있습니다.',['N16_4'])
    if trip['overnight']:
        if inputs['lodging_not_claimed']:
            if lodging or nights:
                block('LODGING_NOT_CLAIMED','숙박비 미청구 시 포함한 숙박 거래와 청구 숙박일을 비워 주세요.',['N28'])
        elif not nights or not lodging or not inputs['lodging_scope_confirmed']:
            block('LODGING_DETAILS','청구할 실제 숙박일·숙박 지역과 포함된 거래의 숙박 범위를 확인하세요.',['N16_4','M_LODGING'])
    elif inputs['lodging_not_claimed'] and (nights or lodging):
        block('LODGING_DETAILS','숙박비 미청구와 숙박 거래가 충돌합니다.',['N16_4'])
    if errors: return result()
    denominator=pack['rates']['vehicle_daily_denominator']
    daily=rates['daily']*days-rates['daily']//denominator*len(vehicles)
    meal=rates['meal_daily']*days
    cap=sum(rates['lodging_caps'][n['region']] for n in nights) if rates['lodging_mode']=='capped_actual' else None
    allowed_lodging=min(lodging,cap) if cap is not None else lodging
    table_ref=rates['clause_id']
    night_rates=[{**n,'region_label':table['regions'][n['region']] if table else n['region'],
                  'cap':rates['lodging_caps'][n['region']] if cap is not None else None} for n in nights]
    line('transport','운임',transport,f"포함한 {rates['rail_class']+' 기준 철도' if trip['transport']=='철도' else trip['transport']} 실비 {transport:,}원",['N10' if trip['transport']=='철도' else 'N15' if trip['transport']=='관용차' else 'N13',table_ref],{'transaction_ids':[r['id'] for r in included if r['category']=='transport']})
    line('daily','일비',daily,f"{rates['daily']:,}원 × {days}일 - {rates['daily']//denominator:,}원 × 차량이용 {len(vehicles)}일",['N5','N16_3',table_ref,'M_VEHICLE'],{'unit_amount':rates['daily'],'days':days,'vehicle_dates':vehicles,'vehicle_daily_denominator':denominator})
    line('meal','식비',meal,f"{rates['meal_daily']:,}원 × {days}일 (식사 제공 없음)",['N5','N16_5',table_ref],{'unit_amount':rates['meal_daily'],'days':days})
    lodging_formula=f"min(실비 {lodging:,}원, 숙박일별 상한 합계 {cap:,}원)" if cap is not None else f"제1호 숙박 실비 {lodging:,}원 (제2호 지역별 상한 적용 안 함)"
    line('lodging','숙박비',allowed_lodging,lodging_formula,['N16_1','N16_4',table_ref,'M_LODGING'],{'actual':lodging,'cap_total':cap,'over_cap':max(0,lodging-cap) if cap is not None else 0,'lodging_mode':rates['lodging_mode'],'nights':nights,'night_rates':night_rates,'transaction_ids':[r['id'] for r in included if r['category']=='lodging']})
    result_data=result()
    if cap is not None and lodging>cap: result_data['warnings'].append('숙박비 상한 초과분은 제외했습니다. 제16조제1항의 예외 추가지급은 자동 인정하지 않습니다.')
    return result_data
