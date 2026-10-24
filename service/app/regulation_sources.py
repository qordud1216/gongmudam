"""허용된 공식 사이트만 조회한다. PDF는 바이트, HTML은 본문·표·첨부 식별자를 비교한다."""
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urlsplit, parse_qs, quote, urljoin
from urllib.request import Request, build_opener, HTTPRedirectHandler
import difflib, html, re
from lxml import html as dom
from . import regulation_registry as registry, travel_rates

HOSTS={'law.go.kr','www.law.go.kr','www.mpm.go.kr'}
CURRENT={
 'national':('https://www.law.go.kr/법령/공무원여비규정','lsiSeq'),
 'gyeonggi':('https://www.law.go.kr/자치법규/경기도공무원여비조례','ordinSeq'),
 'national_training':('https://www.law.go.kr/행정규칙/공무원인재개발업무처리지침','admRulSeq'),
 'local_training':('https://www.law.go.kr/행정규칙/지방공무원교육훈련운영지침','admRulSeq'),
 'guide':('https://www.mpm.go.kr/mpm/info/resultPay/payBoard/?boardId=bbs_0000000000000035&mode=list','guide'),
}

def safe_url(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None,443):raise ValueError('공식 HTTPS 출처가 아닙니다.')
    return quote(url,safe=':/?=&%+;,')

class Redirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return super().redirect_request(req,fp,code,msg,headers,safe_url(newurl))

def fetch(url):
    request=Request(safe_url(url),headers={'User-Agent':'SeomuAssistant-regulation-monitor/1.0','Cache-Control':'no-cache'})
    with build_opener(Redirect).open(request,timeout=35) as r:
        safe_url(r.url);raw=r.read(12*1024*1024+1)
        if not raw or len(raw)>12*1024*1024:raise ValueError('원문이 비어 있거나 용량 한도를 넘었습니다.')
        return raw

class Material(HTMLParser):
    def __init__(self):super().__init__();self.skip=0;self.rows=[];self.current='';self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','head'):self.skip+=1
        if self.skip:return
        if tag in ('p','td','th','li','h1','h2','h3','h4','h5','h6','br','div','tr'):self.flush()
        for k,v in attrs:
            if v and k in ('src','data') and tag in ('img','object','embed','iframe'):
                self.links.append(tag+':'+v)
            if v and (k in ('href','onclick','name','value','id')):
                self.links.extend(re.findall(r'(?:flSeq[=\W]+|flDownload\([\W]*)(\d{6,})',v))
                if k=='id' and v.startswith('svByl'):
                    self.links.append(dict(attrs).get('name',''))
    def handle_endtag(self,tag):
        if tag in ('script','style','head'):
            self.skip=max(0,self.skip-1);return
        if not self.skip and tag in ('p','td','th','li','div','tr'):self.flush()
    def handle_data(self,data):
        if not self.skip:self.current+=data
    def flush(self):
        value=re.sub(r'\s+','',self.current);self.current=''
        if value:self.rows.append(value)

def material(raw):
    p=Material();p.feed(raw.decode('utf-8-sig'));p.flush()
    if len(''.join(p.rows))<100 or not any('제1조' in s or '제1장' in s or '목적' in s for s in p.rows):raise ValueError('정상 법령·지침 본문을 확인하지 못했습니다.')
    p.links.extend(re.findall(r'flSeq[=\W]+(\d{6,})',raw.decode('utf-8-sig')))
    return p.rows+['첨부식별자:'+','.join(sorted(set(p.links)))]

def source_material(key,raw,source):
    """The linked-law page contains multiple independent laws, not one document.

    Match identity and the pinned version before selecting the target's sibling
    blocks. A layout/identity failure is an error, never an unchanged result.
    Annex PDFs remain separately byte-checked sources in the same run.
    """
    if key!='national':return material(raw)
    tree=dom.fromstring(raw.decode('utf-8-sig'),parser=dom.HTMLParser(encoding='utf-8'))
    headings=tree.xpath('//h2[@id="009402"]')
    if len(headings)!=1:raise ValueError('공무원 여비 규정의 고유 본문을 확인하지 못했습니다.')
    heading=headings[0];header=heading.getparent();parent=header.getparent()
    if re.sub(r'\s+','',''.join(heading.itertext()))!='공무원여비규정' or header.get('id')!='conTop' or parent.get('id')!='linkedJoContent':
        raise ValueError('공무원 여비 규정의 문서 식별·본문 구조가 다릅니다.')
    header_html=dom.tostring(header,encoding='unicode')
    ids=re.findall(r'lsiSeq=(\d+)',header_html)
    if ids!=[baseline_id(source,'lsiSeq')]:raise ValueError('공무원 여비 규정 본문의 버전 연결이 등록 기준과 다릅니다.')
    blocks=[header]
    for sibling in header.itersiblings():
        if not isinstance(sibling.tag,str):continue
        if sibling.xpath('.//h2'):
            if sibling.get('id')!='conTop':raise ValueError('연계 법령 본문의 경계가 불명확합니다.')
            break
        blocks.append(sibling)
    else:raise ValueError('연계 법령 본문의 종료 경계를 확인하지 못했습니다.')
    selected=''.join(dom.tostring(block,encoding='unicode',with_tail=False) for block in blocks).encode('utf-8')
    rows=material(selected)
    # Missing/truncated content must not silently certify a partial document.
    joined=''.join(rows)
    if not all(marker in joined for marker in ('제1조(','제8조의2(','제16조(','제18조(','제31조(')):
        raise ValueError('공무원 여비 규정의 필수 조문을 모두 확인하지 못했습니다.')
    return rows

def nonmaterial_reviews(pack,items,checked):
    """Reassess only archived cross-law false positives after a full live check.

    Any real change, failed request, version mismatch or missing evidence keeps
    the prior hold. This is equality verification, never approval of new rules.
    """
    if not items or not checked.get('complete') or checked.get('errors') or checked.get('changes'):return []
    records=checked.get('records',[]);source=pack['sources']['national']
    if {r['source_id'] for r in records if r.get('kind')=='source'}!=set(pack['sources']):return []
    if {r['source_id'] for r in records if r.get('kind')=='current_index'}!=set(CURRENT):return []
    current=next((r for r in records if r.get('kind')=='current_index' and r['source_id']=='national'),{})
    live=next((r for r in records if r.get('kind')=='source' and r['source_id']=='national'),{})
    expected=baseline_id(source,'lsiSeq')
    if current.get('expected')!=expected or current.get('observed')!=expected or not live.get('same_content') or live.get('version_changed'):return []
    reviews=[]
    for item in items:
        if item['signature']!=registry.signature(pack) or item.get('resolution'):continue
        targets=item.get('sources',[])
        if len(targets)!=1:continue
        change=targets[0]
        if change['source_id']!='national' or change['old_sha']!=source['sha256'] or change['previous_version']!=change['current_version']:continue
        try:
            snapshots=[]
            for digest in (change['old_sha'],change['new_sha']):
                raw=(registry.OBJECTS/digest).read_bytes()
                if registry.sha(raw)!=digest:raise ValueError('보존 원문 해시 불일치')
                snapshots.append(source_material('national',raw,source))
            if snapshots[0]!=snapshots[1]:continue
            content_sha=registry.sha(registry.dumps(snapshots[0]).encode())
            reviews.append(dict(id=item['id'],revision=item['revision'],kind='linked_law_scope_v1',source_id='national',
                old_sha=change['old_sha'],new_sha=change['new_sha'],scoped_sha256=content_sha,current_id=expected,
                live_source_sha256=live['sha256'],signature=registry.signature(pack)))
        except (ValueError,OSError,UnicodeError):continue
    return reviews

def version_id(raw,param):
    text=raw.decode('utf-8-sig')
    if param=='guide':
        matches=re.findall(r'공무원보수\s*등의\s*업무지침\(인사혁신처예규\s*제(\d+)호\)\.pdf',text)
        if not matches:raise ValueError('최신 보수 업무지침 PDF 게시물을 확인하지 못했습니다.')
        return matches[0]
    # Only the current lawService iframe is authoritative, not an arbitrary link in the page.
    frames=re.findall(r'<iframe\b[^>]*\bsrc=["\']([^"\']+)',text,re.I)
    values=[parse_qs(urlsplit(html.unescape(s)).query).get(param,[''])[0] for s in frames]
    values=[x for x in values if x.isdecimal()]
    if len(values)!=1:raise ValueError('현행 법령 연결 식별자가 불명확합니다.')
    return values[0]

def baseline_id(source,param):
    if param=='guide':return re.search(r'제(\d+)호',source['version']).group(1)
    value=parse_qs(urlsplit(source['url']).query).get(param,[''])[0]
    if not value.isdecimal():raise ValueError('등록 원문의 현행 식별자가 없습니다.')
    return value

def guide_attachment(index):
    text=index.decode('utf-8-sig')
    # Select the row carrying the newest matching PDF, rather than a generic top notice.
    rows=re.findall(r'<tr\b[^>]*>(.*?)</tr>',text,re.I|re.S)
    row=next((r for r in rows if re.search(r'공무원보수\s*등의\s*업무지침\(인사혁신처예규\s*제\d+호\)\.pdf',r)),None)
    if not row:raise ValueError('최신 업무지침 게시물 행이 없습니다.')
    ids=re.findall(r'cntId=(\d+)',row)
    if not ids:raise ValueError('최신 업무지침 게시물 연결이 없습니다.')
    view_url='https://www.mpm.go.kr/mpm/info/resultPay/payBoard/?boardId=bbs_0000000000000035&mode=view&cntId='+ids[0]
    raw=fetch(view_url);view=raw.decode('utf-8-sig')
    anchors=re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>',view,re.I|re.S)
    candidates=[]
    for href,label in anchors:
        if re.search(r'공무원보수\s*등의\s*업무지침\(인사혁신처예규\s*제\d+호\)\.pdf',label):
            if version_id(label.encode(),'guide')!=version_id(index,'guide'):raise ValueError('최신 게시 목록과 첨부의 지침 버전이 다릅니다.')
            path=re.search(r"Jnit_boardDownload\('(/board/file/[A-Za-z0-9_/-]+)'",html.unescape(href))
            if path:candidates.append(urljoin(view_url,path[1]))
    if len(candidates)!=1:raise ValueError('최신 업무지침 PDF 첨부 연결이 불명확합니다.')
    return candidates[0],dict(kind='attachment_index',source_id='guide',url=view_url,sha256=registry.store_object(raw))

def changed_body(key,new_id):
    endpoint={'national':'lsInfoR.do?lsiSeq=','gyeonggi':'ordinInfoR.do?ordinSeq=',
              'national_training':'admRulLsInfoR.do?admRulSeq=','local_training':'admRulLsInfoR.do?admRulSeq='}.get(key)
    return 'https://www.law.go.kr/LSW/'+endpoint+new_id+'&chrClsCd=010202' if endpoint else None

def national_annexes(source):
    """Resolve the two calculation PDFs from the actual current law, not old aliases."""
    expected=baseline_id(source,'lsiSeq')
    url=f'https://www.law.go.kr/LSW/lsInfoR.do?lsiSeq={expected}&lsId=009402&efYd={source["effective_date"].replace("-","")}&chrClsCd=010202'
    raw=fetch(url);tree=dom.fromstring(raw.decode('utf-8-sig'),parser=dom.HTMLParser(encoding='utf-8'))
    for identity,value in (('lsiSeq',expected),('lsId','009402'),('efYd',source['effective_date'].replace('-',''))):
        if tree.xpath(f'//input[@id="{identity}"]/@value')!=[value]:raise ValueError('현행 별표 연결의 법령 식별자가 다릅니다.')
    if sum(re.sub(r'\s+','',''.join(n.itertext()))=='공무원여비규정' for n in tree.xpath('//h2'))!=1:
        raise ValueError('현행 별표 연결의 법령명이 다릅니다.')
    found={}
    for item in tree.xpath('//li'):
        covers=item.xpath('./span[contains(concat(" ",normalize-space(@class)," ")," pcf_cover ")]')
        if len(covers)!=1:continue
        label=re.sub(r'\s+','',''.join(covers[0].itertext()))
        number=re.match(r'\[별표([12])\]',label)
        if not number:continue
        key='travel_annex'+number[1]
        names=item.xpath('.//div[starts-with(@id,"svByl")]/@name')
        pdfs={parse_qs(urlsplit(html.unescape(a.get('href',''))).query).get('flSeq',[''])[0]
              for a in covers[0].xpath('.//a[.//img[starts-with(@alt,"PDF")]]')}
        if key in found or len(names)!=1 or not names[0].isdecimal() or pdfs!={names[0]}:raise ValueError('현행 여비 별표 PDF 연결이 불명확합니다.')
        found[key]='https://www.law.go.kr/LSW/flDownload.do?flSeq='+names[0]
    if set(found)!={'travel_annex1','travel_annex2'}:raise ValueError('현행 여비 별표 1·2를 모두 확인하지 못했습니다.')
    return found,dict(kind='attachment_index',source_id='national',url=url,sha256=registry.store_object(raw))

def compare(pack):
    records=[];changes=[];errors=[];current={};current_raw={};overrides={}
    def get(item):
        key,url=item
        try:
            raw=fetch(url);return key,raw,None
        except Exception as e:return key,None,str(e)[:400]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for key,raw,error in pool.map(get,[(k,v[0]) for k,v in CURRENT.items()]):
            if error:errors.append(key+': '+error);continue
            digest=registry.store_object(raw);param=CURRENT[key][1]
            try:
                observed=version_id(raw,param);expected=baseline_id(pack['sources'][key],param)
                current[key]=(expected,observed)
                current_raw[key]=raw
                records.append(dict(kind='current_index',source_id=key,url=CURRENT[key][0],sha256=digest,expected=expected,observed=observed))
            except Exception as e:errors.append(key+': '+str(e))
        if 'guide' in current_raw:
            try:
                overrides['guide'],record=guide_attachment(current_raw['guide']);records.append(record)
            except Exception as e:errors.append('guide_attachment: '+str(e)[:400])
        if 'national' in current and current['national'][0]==current['national'][1]:
            try:
                annexes,record=national_annexes(pack['sources']['national']);overrides.update(annexes);records.append(record)
            except Exception as e:errors.append('national_attachments: '+str(e)[:400])
        sources=pack['sources']
        for key,raw,error in pool.map(get,[(k,overrides.get(k) or s.get('review_url') or s.get('original_url') or s['url']) for k,s in sources.items()]):
            source=sources[key]
            if error:errors.append(key+': '+error);continue
            try:
                old=travel_rates.source_path(source).read_bytes()
                if registry.sha(old)!=source['sha256']:raise ValueError('등록 원문 해시가 다릅니다. 자동 갱신 불가')
                pdf=source['file'].endswith('.pdf')
                if pdf and (not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-2048:]):raise ValueError('정상 PDF 원문이 아닙니다.')
                version_changed=key in current and current[key][0]!=current[key][1]
                candidate_url=overrides.get(key) or source.get('review_url') or source['url']
                compared_new=not version_changed
                if version_changed and not pdf:
                    candidate=changed_body(key,current[key][1])
                    try:
                        new_raw=fetch(candidate);material(new_raw);raw=new_raw;candidate_url=candidate;compared_new=True
                    except Exception:
                        # Detection remains actionable if a new-version body cannot yet be extracted.
                        compared_new=False
                before=[] if pdf else source_material(key,old,source)
                # An unapproved new-version body may use a different layout.
                # It is reported for review and can never renew the certificate.
                after=[] if pdf else (material(raw) if version_changed else source_material(key,raw,source))
                digest=registry.store_object(raw)
                same=registry.sha(old)==digest if pdf else before==after
                records.append(dict(kind='source',source_id=key,url=candidate_url,registered_url=source.get('review_url') or source['url'],sha256=digest,same_bytes=digest==source['sha256'],same_content=same,version_changed=version_changed))
                if not same or version_changed:
                    # Never attribute text from a pinned historical URL to a newly discovered version.
                    diff=[]
                    if not pdf:
                        for tag,i,j,k,l in difflib.SequenceMatcher(None,before,after,autojunk=False).get_opcodes():
                            if tag!='equal':diff.append(dict(op=tag,old='\n'.join(before[i:j])[:2400],new='\n'.join(after[k:l])[:2400]))
                    changes.append(dict(source_id=key,title=source['title'],change_kind='현행 버전 변경' if version_changed else ('PDF 원본 변경' if pdf else '본문·표·첨부 변경'),
                        previous_version=source['version'],current_version=('현행 식별자 '+current[key][1]) if version_changed else source['version'],
                        old_sha=source['sha256'],new_sha=digest,original_url=source['url'],candidate_url=candidate_url if compared_new or pdf else CURRENT[key][0],
                        before_text='\n'.join(x['old'] for x in diff[:10]) if diff else ('PDF 원본 '+source['sha256'] if pdf else '등록된 현행 식별자 '+current[key][0]),
                        after_text='\n'.join(x['new'] for x in diff[:10]) if diff else ('PDF 원본 '+digest+' · 표·조문을 원문에서 검토하세요.' if pdf else '새 현행 식별자 '+current[key][1]+' · 새 본문·시행일 대조 필요'),
                        delta=diff[:20],comparison_complete=not pdf and compared_new,effective_date=None))
            except Exception as e:errors.append(key+': '+str(e)[:400])
    # A version change must be reported even if its pinned body download failed.
    for key,(old,new) in current.items():
        if old!=new and not any(x['source_id']==key for x in changes):
            s=pack['sources'][key]
            changes.append(dict(source_id=key,title=s['title'],change_kind='현행 버전 변경 · 본문 확인 미완료',previous_version=s['version'],current_version='현행 식별자 '+new,
                old_sha=s['sha256'],new_sha=registry.sha(new.encode()),original_url=s['url'],candidate_url=CURRENT[key][0],before_text='현행 식별자 '+old,after_text='현행 식별자 '+new,
                delta=[],comparison_complete=False,effective_date=None))
    complete=len([r for r in records if r['kind']=='source'])==len(pack['sources']) and len(current)==len(CURRENT) and not errors
    return dict(records=records,changes=changes,errors=errors,complete=complete)
