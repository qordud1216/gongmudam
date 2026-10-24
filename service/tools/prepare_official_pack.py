"""Prepare paragraph-preserving article excerpts; keep downloaded originals separately."""
from html.parser import HTMLParser
from pathlib import Path
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'reference_data/official-20261020'
class Node:
 def __init__(self,tag='',attrs=()):self.tag=tag;self.attrs=dict(attrs);self.children=[]
 def raw_text(self):
  if self.tag=='img':return self.attrs.get('alt','')
  return ''.join(c if isinstance(c,str) else c.raw_text() for c in self.children)
 def text(self):return re.sub(r'\s+',' ',self.raw_text()).strip()
 def walk(self):
  yield self
  for c in self.children:
   if isinstance(c,Node):yield from c.walk()
class Tree(HTMLParser):
 def __init__(self,text):
  super().__init__(convert_charrefs=True);self.root=Node();self.stack=[self.root];self.feed(text)
 def handle_starttag(self,t,a):
  n=Node(t,a);self.stack[-1].children.append(n)
  if t not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:self.stack.append(n)
 def handle_endtag(self,t):
  for i in range(len(self.stack)-1,0,-1):
   if self.stack[i].tag==t:del self.stack[i:];break
 def handle_data(self,s):self.stack[-1].children.append(s)
def articles(key):
 tree=Tree((BASE/(key+'.html')).read_text(encoding='utf-8'))
 for n in tree.root.walk():
  if 'lawcon' not in n.attrs.get('class','').split():continue
  ps=[p.text() for p in n.walk() if p.tag=='p' and p.text()]
  if ps and (m:=re.match(r'^(제\d+조(?:의\d+)?\([^)]*\))',ps[0])):yield m[1],ps
def build():
 downloads={v['key']:v for v in json.loads((BASE/'downloads.json').read_text(encoding='utf-8'))}
 rules=[('travel','공무원 여비 규정','2026-10-02','대통령령 제36728호','인사혁신처','국가공무원 · 지방공무원 적용은 해당 여비 조례 확인','법령·규정',{'제8조의2','제16조','제18조'}),
        ('leave_article','지방공무원 복무규정','2026-10-02','대통령령 제36728호','행정안전부','지방공무원','법령·규정',{'제7조의5'}),
        ('accounting_current','지방자치단체 회계관리에 관한 훈령','2026-07-06','행정안전부훈령 제446호','행정안전부','지방자치단체 회계업무','기관 지침',{'제115조','제120조','제121조'}),
        ('leave_annual','지방공무원 복무규정','2026-10-02','대통령령 제36728호','행정안전부','지방공무원','법령·규정',{'제7조'}),
        ('leave_official','지방공무원 복무규정','2026-10-02','대통령령 제36728호','행정안전부','지방공무원','법령·규정',{'제7조의6'}),
        ('leave_special','지방공무원 복무규정','2026-10-02','대통령령 제36728호','행정안전부','지방공무원','법령·규정',{'제7조의7'}),
        ('goods_inspection','지방자치단체를 당사자로 하는 계약에 관한 법률','2026-10-20','법률 제22081호','행정안전부','지방자치단체 물품·계약업무','법령·규정',{'제17조'}),
        ('goods_payment','지방자치단체를 당사자로 하는 계약에 관한 법률','2026-10-20','법률 제22081호','행정안전부','지방자치단체 물품·계약업무','법령·규정',{'제18조'})]
 out=BASE/'excerpts';out.mkdir(exist_ok=True);records=[]
 for key,title,effective,number,issuer,scope,kind,wanted in rules:
  seen=set()
  for label,paragraphs in articles(key):
   number_only=label.split('(')[0]
   if number_only not in wanted or number_only in seen:continue
   seen.add(number_only);text='\n'.join(paragraphs)+'\n';path=out/(title+'_'+number_only+'.txt');path.write_text(text,encoding='utf-8')
   source=downloads[key];url=source['url']
   if key=='accounting_current':url='https://www.law.go.kr/admRulLsInfoP.do?admRulSeq=2100000281370'
   records.append(dict(title=title,article=label,effective_date=effective,publication=number,issuer=issuer,institution=scope,kind=kind,source_url=url,download_url=source['url'],retrieved_at=source['retrieved_at'],raw_file=source['file'],raw_sha256=source['raw_sha256'],filename=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),scope='해당 조항 본문 발췌 · 별표·부칙·기관 조례 미포함',paragraphs=len(paragraphs)))
  if seen!=wanted:raise ValueError(f'{title}: missing {wanted-seen}')
 manifest=BASE/'manifest.json'
 extended=[r for r in json.loads(manifest.read_text(encoding='utf-8')) if r.get('collection')=='v40'] if manifest.exists() else []
 manifest.write_text(json.dumps(records+extended,ensure_ascii=False,indent=2),encoding='utf-8');print('Prepared',len(records),'article excerpts')
 if (BASE/'local_budget_2026.pdf').is_file():
  from tools.prepare_budget_pack import build as budget_build
  budget_build()
if __name__=='__main__':build()
