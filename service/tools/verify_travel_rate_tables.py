"""로컬/분리 시연 앱에서 공식 별표 계산을 HTTP로 검증. 명시적인 합성 출장 3건/앱만 생성."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import urllib.request
import zipfile
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]


def run(port):
    base=f'http://127.0.0.1:{port}/api/travel'
    def request(path,body=None,method=None,raw=False):
        payload=None if body is None else json.dumps(body,ensure_ascii=False).encode('utf-8')
        req=urllib.request.Request(base+path,data=payload,method=method or ('POST' if payload is not None else 'GET'),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=30) as response:
            data=response.read()
        return data if raw else json.loads(data)
    def create(transport='철도',inside=False):
        case=request('/cases',dict(organization_id='national-general',work_pattern='일반근무',destination='부산',
            purpose='[합성 v41] 등록 금액표 검증',start_date='2026-10-15',end_date='2026-10-15' if inside else '2026-10-17',
            transport=transport,overnight=not inside,meals_provided=False))
        if not inside:
            text='2026-10-15 20:00 합성호텔 240,000원'
            if transport!='관용차':text='2026-10-15 08:00 코레일 100원\n'+text
            case=request(f"/cases/{case['id']}/evidence",dict(version=case['version'],source_type='receipt_text',text=text))
            for index in range(len(case['review']['transactions'])):
                row=case['review']['transactions'][index]
                case=request(f"/cases/{case['id']}/transactions/{row['id']}",dict(version=case['version'],decision='include',reason='합성 v41 자동 검증 자료: 실제 청구 아님',category=row['category']),method='PATCH')
        return case
    records=[]
    def calculate(case,label,expected,**changes):
        values=dict(version=case['version'],grade='group2',group1_standard_confirmed=False,journey_area='domestic',
            conditions_confirmed=True,ordinary_fare_confirmed=True,lodging_scope_confirmed=True,
            lodging_nights=[dict(night='2026-10-15',region='metropolitan'),dict(night='2026-10-16',region='metropolitan')])
        case=request(f"/cases/{case['id']}/calculate",{**values,**changes})
        result=case['calculation']['result']
        assert result['estimated_total']==expected,(port,label,expected,result)
        assert result['payable_amount'] is None
        assert not case['calculation']['stale']
        for line in result['lines']:
            assert line['basis'] and all(ref['source_sha256'] for ref in line['basis'])
        records.append(dict(label=label,expected=expected,passed=True,case_id=case['id'],result=result))
        return case
    cases={}
    for mode in ('rail','official'):
        case=create('철도' if mode=='rail' else '관용차')
        for grade in ('group1','group2'):
            for region,cap in [('seoul',200000),('metropolitan',160000),('other',140000)]:
                options=[('none',[],75000),('partial',['2026-10-16'],62500)] if mode=='rail' else [('all',['2026-10-15','2026-10-16','2026-10-17'],37500)]
                for vehicle,dates,daily in options:
                    expected=(100 if mode=='rail' else 0)+daily+75000+(240000 if grade=='group1' else cap)
                    case=calculate(case,f'{grade}/{region}/{vehicle}',expected,grade=grade,group1_standard_confirmed=grade=='group1',vehicle_dates=dates,
                        lodging_nights=[dict(night='2026-10-15',region=region),dict(night='2026-10-16',region=region)])
                    refs=case['calculation']['result']['lines'][0]['basis']
                    assert any(ref['id']=='T2_'+grade.upper() and ref.get('registered_excerpt_sha256') for ref in refs)
        cases[mode]=case
    local=create(inside=True)
    for grade in ('group1','group2'):
        for minutes,car,assigned,amount in [(239,False,False,10000),(240,False,False,20000),(239,True,False,0),(240,True,False,10000),(240,True,True,0)]:
            local=calculate(local,f'inside/{grade}/{minutes}/{car}/{assigned}',amount,grade=grade,travel_scope='inside',within_minutes=minutes,
                round_trip_km=3,assigned_vehicle=assigned,vehicle_dates=['2026-10-15'] if car else [],lodging_nights=[])
    case=cases['rail']
    case=calculate(case,'unconfirmed payment group',None,grade='unconfirmed')
    case=calculate(case,'group1 exception not confirmed',None,grade='group1')
    case=calculate(case,'overseas domestic-table rejection',None,journey_area='overseas')
    case=calculate(case,'restore supported review result',297600,vehicle_dates=['2026-10-16'])
    sources=[]
    bundle=request('/legal-packs')
    for key in ('travel_annex1','travel_annex2'):
        source=bundle['sources'][key]
        raw=request('/legal-sources/'+key+'?sha256='+source['sha256'],raw=True)
        assert hashlib.sha256(raw).hexdigest()==source['sha256']
        sources.append(dict(id=key,sha256=source['sha256'],excerpt_sha256=source['excerpt_sha256'],official_url=source['url'],passed=True))
    draft=request(f"/cases/{case['id']}/drafts",dict(version=case['version']))
    raw=request('/drafts/'+draft['id']+'/package',raw=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        digests={hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist() if name.startswith('근거원문/')}
        assert all(source['sha256'] in digests for source in sources)
    html=request('/drafts/'+draft['id']+'/print',raw=True).decode('utf-8')
    assert '297,600원' in html and '별표 2 제2호' in html
    return dict(port=port,passed=True,synthetic=True,cases={**{k:v['id'] for k,v in cases.items()},'inside':local['id']},
        checks=len(records),records=records,sources=sources,draft_id=draft['id'],package_sha256=hashlib.sha256(raw).hexdigest(),
        rulepack_version=bundle['version'],coverage_start=bundle['coverage_start'],verified_through=bundle['verified_through'])


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--ports',nargs='+',type=int,default=[8766,8767])
    parser.add_argument('--output',type=Path,default=ROOT.parent/'work/travel-rates-v41-live.json')
    args=parser.parse_args()
    assert all(port in (8766,8767) for port in args.ports)
    data=dict(checked_at=datetime.now(timezone.utc).isoformat(),runs=[run(port) for port in args.ports])
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(report=str(args.output),runs=[{k:r[k] for k in ('port','passed','checks','rulepack_version')} for r in data['runs']]),ensure_ascii=False,indent=2))
