"""대조 완료한 원문 증거로만 새 규정팩 발행. 과거 배포본은 수정하지 않는다."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib,json,sys,re
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from recheck_travel_sources import URLS,LATEST,paragraph_digest


def build():
    folder=ROOT/'reference_data/travel-recheck-20261020'
    rows={r['id']:r for r in json.loads((folder/'downloads.json').read_text(encoding='utf-8'))}
    pack=json.loads((ROOT/'app/rulepacks/domestic_tables_2026_10.json').read_text(encoding='utf-8'))
    checked=set()
    for key in URLS:
        record=rows[key];raw=(folder/record['file']).read_bytes();source=pack['sources'][key]
        assert hashlib.sha256(raw).hexdigest()==record['sha256']
        old=(ROOT/'reference_data'/source.get('collection','travel')/source['file']).read_bytes()
        assert hashlib.sha256(old).hexdigest()==source['sha256']
        if raw!=old:
            assert record['file'].endswith('.html') and paragraph_digest(old)==paragraph_digest(raw)
        checked.add(datetime.fromisoformat(record['retrieved_at']).astimezone(timezone(timedelta(hours=9))).date().isoformat())
        if key not in ('travel_annex1','travel_annex2'):
            source.update(collection=folder.name,file=record['file'],sha256=record['sha256'])
        source.update(verified_on=next(iter(checked)),review_url=record['url'])
    assert len(checked)==1
    day=next(iter(checked))
    for key in LATEST:
        row=rows[key];assert hashlib.sha256((folder/row['file']).read_bytes()).hexdigest()==row['sha256']
    identifiers={'national_current':'lsiSeq=290313','national_training_current':'admRulSeq=2100000286938',
                 'local_training_current':'admRulSeq=2100000284386','gyeonggi_current':'ordinSeq=2136163'}
    for key,value in identifiers.items():assert value in (folder/rows[key]['file']).read_text(encoding='utf-8')
    guide=(folder/'guide_current.html').read_text(encoding='utf-8')
    assert re.findall(r'공무원보수 등의 업무지침\(인사혁신처예규 제(\d+)호\)\.pdf',guide)[0]=='226'
    pack.update(version=day+'.2',engine_version='domestic-reviewed-2.1',verified_through=day)
    pack['validity_policy']=dict(mode='reviewed_and_future_estimate',reviewed_on=day,
        preview_until=day[:4]+'-12-31',known_end_exclusive=None,
        note='원문 확인일은 법령 종료일과 다릅니다. 확인일 이후의 예정 출장은 사전산정이며, 종료 후 최신 기준을 다시 확인해야 합니다.')
    pack['source_review']=dict(collection=folder.name,manifest='downloads.json',
        manifest_sha256=hashlib.sha256((folder/'downloads.json').read_bytes()).hexdigest(),sources=list(URLS))
    target=ROOT/'app/rulepacks/domestic_reviewed_2026_10.json'
    target.write_text(json.dumps(pack,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(target.name,pack['version'],'reviewed',day,'preview',pack['validity_policy']['preview_until'])


if __name__=='__main__':build()
