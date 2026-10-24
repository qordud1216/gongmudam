"""공식 원문 재다운로드·배포 사본 대조. 다른 원문이면 자동으로 확인 기간을 늘리지 않는다."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, quote
from html.parser import HTMLParser
import hashlib
import json
import re
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reference_data/travel-recheck-20261020'
URLS={
    'national':'https://www.law.go.kr/lsLinkCommonInfo.do?lspttninfSeq=57051',
    'gyeonggi':'https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2136163&chrClsCd=010202',
    'guide':'https://www.mpm.go.kr/board/file/bbs_0000000000000035/695/FILE_000000100073530/7aa6b30cca5926d04',
    'national_training':'https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000286938&chrClsCd=010202',
    'national_training_table':'https://www.law.go.kr/LSW/flDownload.do?flSeq=170649721',
    'local_training':'https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000284386&chrClsCd=010202',
    'local_training_table':'https://www.law.go.kr/LSW/flDownload.do?flSeq=168755067',
    'travel_annex1':'https://www.law.go.kr/LSW/flDownload.do?flSeq=169558635',
    'travel_annex2':'https://www.law.go.kr/LSW/flDownload.do?flSeq=169558641',
}
LATEST={
    'national_current':'https://www.law.go.kr/법령/공무원여비규정',
    'national_training_current':'https://www.law.go.kr/행정규칙/공무원인재개발업무처리지침',
    'local_training_current':'https://www.law.go.kr/행정규칙/지방공무원교육훈련운영지침',
    'gyeonggi_current':'https://www.law.go.kr/자치법규/경기도공무원여비조례',
    'guide_current':'https://www.mpm.go.kr/mpm/info/resultPay/payBoard/?boardId=bbs_0000000000000035&mode=list',
}


class Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__();self.active=False;self.rows=[];self.row=''
    def handle_starttag(self,tag,attrs):
        if tag=='p':self.active=True;self.row=''
    def handle_endtag(self,tag):
        if tag=='p' and self.active:
            self.rows.append(re.sub(r'\s+','',self.row));self.active=False
    def handle_data(self,data):
        if self.active:self.row+=data


def paragraph_digest(raw):
    parser=Paragraphs();parser.feed(raw.decode('utf-8'))
    if not parser.rows:raise ValueError('대조할 본문 문단이 없습니다.')
    return hashlib.sha256(json.dumps(parser.rows,ensure_ascii=False).encode()).hexdigest(),len(parser.rows)


def fetch(item):
    key,url=item
    req=urllib.request.Request(quote(url,safe=':/?=&'),headers={'User-Agent':'SeomuAssistant-source-review/1.0'})
    with urllib.request.urlopen(req,timeout=40) as response:
        if urlsplit(response.url).hostname not in {'law.go.kr','www.law.go.kr','www.mpm.go.kr'}:
            raise ValueError('예상하지 않은 출처 주소')
        raw=response.read(10*1024*1024+1)
        if len(raw)>10*1024*1024:raise ValueError('원문 용량 초과')
        final_url=response.url
    suffix='.pdf' if raw.startswith(b'%PDF-') else '.html'
    target=OUT/(key+suffix);target.write_bytes(raw)
    return dict(id=key,url=url,final_url=final_url,file=target.name,sha256=hashlib.sha256(raw).hexdigest(),
                size=len(raw),retrieved_at=datetime.now(timezone.utc).isoformat())


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    pack=json.loads((ROOT/'app/rulepacks/domestic_tables_2026_10.json').read_text(encoding='utf-8'))
    with ThreadPoolExecutor(max_workers=5) as pool:
        records=list(pool.map(fetch,{**URLS,**LATEST}.items()))
    for record in records:
        if record['id'] in pack['sources']:
            source=pack['sources'][record['id']]
            old=ROOT/'reference_data'/source.get('collection','travel')/source['file']
            record['same_bytes']=record['sha256']==source['sha256']
            record['same_as_reviewed']=record['same_bytes']
            if not record['same_bytes'] and record['file'].endswith('.html'):
                before,count=paragraph_digest(old.read_bytes());after,new_count=paragraph_digest((OUT/record['file']).read_bytes())
                record.update(paragraph_sha256=after,previous_paragraph_sha256=before,paragraphs=new_count)
                record['same_as_reviewed']=before==after and count==new_count
        print(record['id'],record['size'],record.get('same_as_reviewed','index'),flush=True)
    (OUT/'downloads.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    assert all(r.get('same_as_reviewed',True) for r in records),'다른 내용의 원문이 있습니다. 변경 부분을 검토하세요.'
    expected={'national_current':'lsiSeq=290313','national_training_current':'admRulSeq=2100000286938',
              'local_training_current':'admRulSeq=2100000284386','gyeonggi_current':'ordinSeq=2136163'}
    for key,identifier in expected.items():
        assert identifier in (OUT/(key+'.html')).read_text(encoding='utf-8'),('현행 버전 변경',key)
    assert '제226호' in (OUT/'guide_current.html').read_text(encoding='utf-8'),'최신 게시물 버전 확인 필요'


if __name__=='__main__':main()
