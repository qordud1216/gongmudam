"""v42 로컬 HTTP 검증. 합성 사례만 추가하며 사용자 출장은 변경하지 않는다."""
from pathlib import Path
import json,urllib.request,hashlib,io,zipfile
ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8766/api/travel'


def call(path,body=None,method=None,raw=False):
    req=urllib.request.Request(BASE+path,data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),
        headers={'Content-Type':'application/json'},method=method or ('POST' if body is not None else 'GET'))
    with urllib.request.urlopen(req,timeout=30) as response:data=response.read()
    return data if raw else json.loads(data)


def prepared(org,start,end,training=False,inside=False):
    c=call('/cases',dict(organization_id=org,work_pattern='일반근무',destination='서울',purpose='[합성 v42] '+('교육 검증' if training else '계산 기간 검증'),
        start_date=start,end_date=end,transport='철도',overnight=not inside,meals_provided=False))
    if inside:return c
    text=start+' 08:00 코레일 100원'
    if not training:text+='\n'+start+' 20:00 합성호텔 120,000원'
    c=call('/cases/'+c['id']+'/evidence',dict(version=c['version'],source_type='receipt_text',text=text))
    for i in range(len(c['review']['transactions'])):
        r=c['review']['transactions'][i]
        c=call('/cases/'+c['id']+'/transactions/'+r['id'],dict(version=c['version'],decision='include',reason='합성 v42 검증: 실제 청구 아님',category=r['category']),method='PATCH')
    return c


def main():
    bundle=call('/legal-packs');assert bundle['version']=='2026-10-20.2'
    before=json.loads((ROOT.parent/'work/travel-period-v42-before.json').read_text(encoding='utf-8'))
    c=call('/cases/'+before['case']['id'])
    assert c['calculation']['result']['estimated_total']==200100
    assert any(e['event_type']=='LEGAL_PACK_UPDATED' for e in c['events'])
    assert call('/drafts/'+before['draft']['id']+'/print',raw=True).decode()==before['old_print']
    records=[dict(label='existing v41 case updated in UI',case_id=c['id'],passed=True,result=c['calculation']['result'],old_draft_preserved=True)]
    def calc(c,label,want,estimate=False,**changes):
        start=c['trip_json']['start_date']
        values=dict(version=c['version'],grade='group2',conditions_confirmed=True,ordinary_fare_confirmed=True,lodging_scope_confirmed=True,
                    lodging_nights=[dict(night=start,region='seoul')])
        c=call('/cases/'+c['id']+'/calculate',{**values,**changes})
        r=c['calculation']['result']
        assert r['estimated_total']==want,(label,r)
        assert r['temporal']['is_estimate']==estimate
        assert r['payable_amount'] is None
        records.append(dict(label=label,case_id=c['id'],passed=True,result=r))
        return c
    for org in ('national-general','gg-province','gg-fire'):
        calc(prepared(org,'2026-10-19','2026-10-20'),org+' completed after19',200100)
    future=calc(prepared('national-general','2026-10-21','2026-10-22'),'future estimate',180100,estimate=True,
        lodging_nights=[dict(night='2026-10-21',region='metropolitan')])
    d=call('/cases/'+future['id']+'/drafts',dict(version=future['version']))
    assert '예정 출장 사전산정' in call('/drafts/'+d['id']+'/print',raw=True).decode()
    assert '예정 출장 사전산정' in call('/drafts/'+d['id']+'/csv',raw=True).decode('utf-8-sig')
    package=call('/drafts/'+d['id']+'/package-check')
    assert any(item['code']=='FUTURE_ESTIMATE' for item in package['checklist'])
    raw=call('/drafts/'+d['id']+'/package',raw=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert any('사전산정' in archive.read(name).decode('utf-8-sig') for name in archive.namelist() if name.endswith('.csv'))
    calc(prepared('national-general','2026-10-20','2026-10-20',inside=True),'inside20 official vehicle',10000,
        travel_scope='inside',within_minutes=240,round_trip_km=3,vehicle_dates=['2026-10-20'],lodging_nights=[])
    from app.travel_demo import definition
    for org in ('national-general','gg-province'):
        t=definition('training')['inputs']['training']
        t.update(entry_date='2026-10-19',completion_date='2026-10-20',teaching_dates=['2026-10-19','2026-10-20'],institution_meal=18000)
        calc(prepared(org,'2026-10-19','2026-10-20',training=True),org+' training after19',108100,lodging_nights=[],training=t)
    sources=[]
    for key,source in bundle['sources'].items():
        data=call('/legal-sources/'+key+'?sha256='+source['sha256'],raw=True)
        assert hashlib.sha256(data).hexdigest()==source['sha256']
        sources.append(dict(id=key,sha256=source['sha256'],verified_on=source['verified_on'],passed=True))
    report=dict(version=bundle['version'],verified_through=bundle['verified_through'],preview_until=bundle['validity_policy']['preview_until'],
        records=records,checks=len(records),sources=sources,old_draft_id=before['draft']['id'],future_case_id=future['id'],future_draft_id=d['id'],
        future_package_sha256=hashlib.sha256(raw).hexdigest(),public_origin_accessed=False)
    target=ROOT.parent/'work/travel-period-v42-live.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(report=str(target),checks=len(records),source_downloads=len(sources),old_draft_preserved=True),ensure_ascii=False))


if __name__=='__main__':
    import sys
    sys.path.insert(0,str(ROOT))
    main()
