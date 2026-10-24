"""로컬 2종 모델의 동일 서무업무 실행과 재현 가능한 검증 기록."""
import hashlib
import json
import time
import uuid
from datetime import date,datetime,timezone
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter,HTTPException
from pydantic import Field
from . import assistant,config,llm
from .travel_models import StrictModel

router=APIRouter(prefix='/api/local-ai',tags=['로컬 AI 실제 구동 검증'])
SCENARIOS={
 'travel':{'title':'출장 정산 절차·서식·근거','query':'2026년 10월 18일 서울 출장 다녀왔어요. 출장 여비 정산 절차와 필요한 서식 및 근거를 알려주세요.','expected_card':'card-travel'},
 'leave':{'title':'교대근무 연가 신청','query':'교대근무자인데 2026년 10월 26일 연가를 쓰려고 합니다. 복무 신청 절차와 필요한 서류를 알려주세요.','expected_card':'card-leave'},
 'purchase':{'title':'물품 납품 검수','query':'소화기가 2026년 10월 19일 납품되었습니다. 물품 구매 검수 절차와 검사 서식을 알려주세요.','expected_card':'card-purchase'}
}


class Run(StrictModel):
    profile: str=Field(min_length=1,max_length=60)
    scenario: str=Field(min_length=1,max_length=30)


def local_profile(name):
    profile=config.active_profile({'llm':{'active':name,'profiles':config.load().get('llm',{}).get('profiles',{})}})
    parsed=urlsplit(profile.get('base_url',''))
    if profile.get('provider')!='openai_compatible' or parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(422,'이 검증 화면은 로컬 HTTP 모델 서버에 등록된 프로필만 사용합니다.')
    return profile


@router.get('/options')
def options():
    profiles=[]
    for name in config.load().get('llm',{}).get('profiles',{}):
        try: p=local_profile(name)
        except (HTTPException,ValueError): continue
        profiles.append({'id':name,'model':p.get('model'),'base_url':p['base_url']})
    try:
        version=httpx.get('http://127.0.0.1:11434/api/version',timeout=3).json()
        installed=httpx.get('http://127.0.0.1:11434/api/tags',timeout=3).json().get('models',[])
    except (httpx.HTTPError,ValueError): version={};installed=[]
    return {'profiles':profiles,'scenarios':[{'id':key,**value} for key,value in SCENARIOS.items()],
            'ollama_version':version.get('version'),'installed_models':installed,
            'notice':'모의 규정·절차 카드로 실제 로컬 LLM의 절차 선택을 검증합니다. 금액·법적 기한의 실제 지급 기준 검증과 구분합니다. 모델 원문은 검증 전 자료입니다.'}


@router.post('/run')
def run(body: Run):
    if body.scenario not in SCENARIOS: raise HTTPException(404,'검증 사례가 없습니다.')
    profile=local_profile(body.profile);scenario=SCENARIOS[body.scenario];started=time.perf_counter()
    with llm.capture_calls() as calls:
        result=assistant.ask(scenario['query'],today=date(2026,10,19),profile_override=profile)
    selected=None
    if calls:
        content=calls[-1]['response'].get('choices',[{}])[0].get('message',{}).get('content','')
        try: selected=llm.extract_json(content).get('card_id')
        except (llm.LLMError,AttributeError): pass
    plan=result.get('plan') or {};steps=plan.get('steps',[])
    checks={
        'actual_model_response':bool(calls) and result['mode']=='llm',
        'model_selected_expected_card':selected==scenario['expected_card'],
        'app_selected_expected_card':plan.get('card',{}).get('id')==scenario['expected_card'],
        'procedure_present':bool(steps),
        'basis_present':any(s.get('basis') for s in steps),
        'required_forms_present':any(s.get('forms') for s in steps) if body.scenario!='leave' else True,
        'next_action_present':bool(result.get('summary'))
    }
    evidence={'id':uuid.uuid4().hex,'created_at':datetime.now(timezone.utc).isoformat(),'scenario_id':body.scenario,'scenario':scenario,
              'profile':body.profile,'requested_model':profile.get('model'),'endpoint':profile['base_url'],
              'response_model':calls[-1]['response'].get('model') if calls else None,
              'elapsed_seconds':round(time.perf_counter()-started,3),'checks':checks,'passed':all(checks.values()),
              'result':result,'model_calls':calls,'data_notice':'합성 검증 사례 · 실제 법령·기관 승인·지급용 아님',
              'role_notice':'LLM은 절차 카드·근거 후보 선택을 보조합니다. 기한·절차 본문은 등록자료로 프로그램이 구성하며 모델 원문을 그대로 채택하지 않습니다.'}
    evidence['form_check_scope']='등록된 서식이 없는 연가 사례는 서식 검사를 해당 없음으로 처리' if body.scenario=='leave' else '등록된 필수 서식 확인'
    evidence['evidence_sha256']=hashlib.sha256(json.dumps(evidence,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return evidence


@router.post('/failure-check')
def failure_check():
    started=time.perf_counter()
    profile={'_name':'local_unavailable_test','provider':'openai_compatible','base_url':'http://127.0.0.1:1/v1','model':'unavailable-local-test','timeout':2,'max_tokens':50}
    result=assistant.ask(SCENARIOS['travel']['query'],today=date(2026,10,19),profile_override=profile)
    return {'created_at':datetime.now(timezone.utc).isoformat(),'test':'닫힌 로컬 포트에 실제 연결 시도','endpoint':profile['base_url'],
            'passed':result['mode']=='fallback' and result.get('plan',{}).get('card',{}).get('id')=='card-travel',
            'elapsed_seconds':round(time.perf_counter()-started,3),'result':result,
            'notice':'모델 서버 장애 시 규칙 기반 안내를 검증한 결과이며 모델 2종 실제 응답 성공 건수에는 포함하지 않습니다.'}
