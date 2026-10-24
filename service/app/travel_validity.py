"""원문 확인일·규정 적용일·예정 출장의 사전산정을 구분한다."""
from datetime import datetime,timezone,timedelta


def today():
    return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


def assess(pack,start,end):
    start=str(start);end=str(end);policy=pack.get('validity_policy') or {}
    result=dict(reviewed_through=pack['verified_through'],coverage_start=pack['coverage_start'],
                preview_until=policy.get('preview_until'),known_end_exclusive=policy.get('known_end_exclusive'),
                is_estimate=False,allowed=False,status='outside_scope')
    if start<pack['coverage_start'] or (policy.get('known_end_exclusive') and end>=policy['known_end_exclusive']):
        return {**result,'message':'출장기간에 맞는 다른 시행본이 필요합니다. 개정 경계를 넘으면 기준을 나누어 검토하세요.'}
    if end<=pack['verified_through']:
        return {**result,'allowed':True,'status':'reviewed','message':'출장기간의 적용 기준을 원문 재확인 범위에서 산정합니다.'}
    if policy.get('mode')=='reviewed_and_future_estimate' and end>today() and end<=policy['preview_until']:
        return {**result,'allowed':True,'status':'future_estimate','is_estimate':True,
                'message':'예정 출장의 사전산정입니다. 여행 종료 후 실제 내역과 그 시점의 최신 규정·지침을 다시 확인해야 합니다.'}
    return {**result,'status':'needs_recheck','message':f"원문 확인일은 {pack['verified_through']}입니다. 해당 출장일의 최신 원문을 다시 확인한 규정팩으로 갱신하세요."}
