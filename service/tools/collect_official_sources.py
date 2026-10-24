"""Download only the explicitly reviewed public law.go.kr source pages."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,urllib.request
ROOT=Path(__file__).resolve().parents[1]
PAGES={
 'travel':'https://www.law.go.kr/lsLinkCommonInfo.do?lspttninfSeq=57051',
 'leave':'https://www.law.go.kr/LSW/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1033630241',
 'accounting':'https://www.law.go.kr/admRulLsInfoP.do?admRulSeq=2100000285992',
 'leave_guideline':'https://www.law.go.kr/admRulInfoP.do?admRulSeq=2100000282706',
 'accounting_current':'https://www.law.go.kr/admRulLsInfoR.do?admRulSeq=2100000281370&chrClsCd=010202',
 'guideline_body':'https://www.law.go.kr/admRulLsInfoR.do?admRulSeq=2100000282706&chrClsCd=010202',
 'leave_article':'https://www.law.go.kr/LSW/lsSideInfoP.do?joNo=0007&joBrNo=05&lsiSeq=290493&urlMode=lsScJoRltInfoR&docCls=jo',
 'leave_annual':'https://www.law.go.kr/LSW/lsSideInfoP.do?joNo=0007&joBrNo=00&lsiSeq=290493&urlMode=lsScJoRltInfoR&docCls=jo',
 'leave_official':'https://www.law.go.kr/LSW/lsSideInfoP.do?joNo=0007&joBrNo=06&lsiSeq=290493&urlMode=lsScJoRltInfoR&docCls=jo',
 'leave_special':'https://www.law.go.kr/LSW/lsSideInfoP.do?joNo=0007&joBrNo=07&lsiSeq=290493&urlMode=lsScJoRltInfoR&docCls=jo',
 'goods_inspection':'https://www.law.go.kr/LSW/lsSideInfoP.do?joNo=0017&joBrNo=00&lsiSeq=291241&urlMode=lsScJoRltInfoR&docCls=jo',
 'goods_payment':'https://www.law.go.kr/LSW/lsSideInfoP.do?joNo=0018&joBrNo=00&lsiSeq=291241&urlMode=lsScJoRltInfoR&docCls=jo',
}
def collect():
 out=ROOT/'reference_data/official-20261020';out.mkdir(parents=True,exist_ok=True);entries=[]
 for key,url in PAGES.items():
  request=urllib.request.Request(url,headers={'User-Agent':'SeomuAssistant-official-source-verification/1.0'})
  with urllib.request.urlopen(request,timeout=40) as response:
   if urllib.parse.urlsplit(response.url).hostname not in {'law.go.kr','www.law.go.kr'}:raise ValueError('Unexpected redirect')
   raw=response.read(8*1024*1024+1)
   if len(raw)>8*1024*1024:raise ValueError('Source too large')
  (out/(key+'.html')).write_bytes(raw)
  entries.append(dict(key=key,url=url,file=key+'.html',raw_sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),retrieved_at=datetime.now(timezone.utc).isoformat()))
  print(key,len(raw),flush=True)
 (out/'downloads.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':collect()
