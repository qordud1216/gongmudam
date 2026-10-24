"""Register the reviewed public excerpts and test real app answers against originals."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,time,io,shutil
import httpx
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'reference_data/official-20261020'
STATE=ROOT.parent/'work/official-v32-registration.json';REPORT=ROOT.parent/'work/official-v32-verification.json'
NAME='[공식 공개원문] 서무 법령·회계지침 · 2026-10-20 수집'
CASES=[
 ('travel-settlement','국가공무원이 출장 후 운임과 숙박비 정산을 신청할 때 신청기한과 증거서류는 어떻게 되나요?','공무원 여비 규정','제8조의2',['2주일 이내','증거서류']),
 ('local-travel','공무원 근무지 내 국내 출장에서 4시간 이상인 경우 여비는 얼마인가요? 공무용 차량 이용 시 감액도 알려주세요.','공무원 여비 규정','제18조',['2만원','1만원을 감액']),
 ('sick-note','지방공무원 병가 일수가 연 6일을 초과하면 의사의 진단서를 첨부해야 하나요?','지방공무원 복무규정','제7조의5',['진단서','6일을 초과']),
 ('card-points','지방자치단체 신용카드 포인트를 개인적으로 써도 되나요? 세입조치는 얼마나 자주 하나요?','지방자치단체 회계관리에 관한 훈령','제120조',['개인적으로 사용할 수 없','연 1회 이상']),
 ('disclosure','지방자치단체 초빙강사료 집행내역 공개 대상 금액과 공개 주기는 무엇인가요?','지방자치단체 회계관리에 관한 훈령','제121조',['500만원','매 반기 후 1개월 이내']),
 ('no-source','양자컴퓨터 희석냉동기 냉각온도 설정값은 무엇인가요?',None,None,[]),
]
def register():
 rows=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'));expected_digests={r['sha256'] for r in rows};assert rows and len(rows)<=30 and len(expected_digests)==len(rows);state={}
 for port in [8766,8767]:
  with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=30) as c:
   c.get('/openapi.json').raise_for_status();existing=c.get('/api/folders/libraries').json();item=next((v for v in existing if v['name']==NAME),None)
   if item:
    v=c.get('/api/folders/libraries/'+item['id']).json()
    if port==8767:
     target=Path(v['files'][0]['path']).resolve().parent;allowed=(ROOT.parent/'work/public-demo-v28b/synthetic-folders').resolve()
     if not target.is_relative_to(allowed):raise ValueError('Public copy must remain in the synthetic-folder root')
     for row in rows:shutil.copy2(BASE/'excerpts'/row['filename'],target/row['filename'])
    r=c.post('/api/folders/libraries/'+v['id']+'/scan',json={'version':v['version']});r.raise_for_status();v=r.json()
   elif port==8766:
    r=c.post('/api/folders/libraries',json={'name':NAME,'roots':[str(BASE/'excerpts')]});r.raise_for_status();v=r.json()
   else:
    data={'name':NAME,'paths':json.dumps(['공식서무근거/'+r['filename'] for r in rows],ensure_ascii=False),'public_consent':'true'}
    files=[('files',(r['filename'],(BASE/'excerpts'/r['filename']).read_bytes(),'text/plain')) for r in rows]
    r=c.post('/api/folders/uploads',data=data,files=files);r.raise_for_status();v=r.json()
   r=c.post('/api/knowledge/libraries/'+v['id']+'/sources',json={'version':v['version'],'file_ids':[f['id'] for f in v['files']],'kind':'참고자료'});r.raise_for_status();sources=r.json()['sources']
   assert len(sources)==len(rows) and {s.get('sha256') for s in sources}==expected_digests and all(s.get('sha256') in expected_digests and s.get('official') and s['current'] for s in sources)
   state[str(port)]={'library_id':v['id'],'registered_count':len(sources),'sources':[dict(title=s['title'],official=s['official']) for s in sources]}
   print('Registered',port,len(sources),flush=True)
 STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
def verify(case_filter=None):
 state=json.loads(STATE.read_text(encoding='utf-8'));key=state['8767']['library_id'];results=[]
 if case_filter and REPORT.exists():results=[c for c in json.loads(REPORT.read_text(encoding='utf-8'))['cases'] if c['id']!=case_filter]
 manifest=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'));originals={r['sha256']:(BASE/'excerpts'/r['filename']).read_text(encoding='utf-8') for r in manifest}
 proof=dict(checked_at=datetime.now(timezone.utc).isoformat(),library_id=key,registration=state,cases=results,not_registered=[dict(title='지방자치단체 회계관리에 관한 훈령 제468호',effective_date='2027-01-01',reason='수집일 이후 시행 예정이므로 현행 근거 등록에서 제외')])
 with httpx.Client(base_url='http://127.0.0.1:8767',timeout=45) as c:
  for case,question,title,article,facts in CASES:
   if case_filter and case!=case_filter:continue
   start=time.monotonic();r=c.post('/api/ask',json={'query':question,'knowledge_library_id':key,'today':'2026-10-20'});r.raise_for_status();answer=r.json();e=answer['knowledge']['evidence']
   exact=all(v['quote'] in originals.get(v['sha256'],'') for v in e)
   matches=[v for v in e if v.get('official',{}).get('title')==title and v.get('official',{}).get('article','').startswith(article)] if title else []
   all_text='\n'.join(v['quote'] for v in matches)
   passed=exact and (bool(matches) and all(f in all_text for f in facts) if title else not e)
   results.append(dict(id=case,question=question,expected_title=title,expected_article=article,expected_facts=facts,mode=answer['mode'],model=answer.get('model'),seconds=round(time.monotonic()-start,2),exact_original_quotes=exact,passed=passed,answer=answer))
   REPORT.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8');print(case,answer['mode'],'PASS' if passed else 'FAIL',flush=True)
 proof['summary']={'passed':sum(r['passed'] for r in results),'total':len(results),'actual_model_answers':sum(r['mode']=='source_llm' for r in results),'all_quotes_exact':all(r['exact_original_quotes'] for r in results)}
 REPORT.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8');print(proof['summary'],flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--register',action='store_true');p.add_argument('--verify',action='store_true');p.add_argument('--case',choices=[c[0] for c in CASES]);p.add_argument('--environment',action='store_true');a=p.parse_args()
 if a.register:register()
 if a.verify:verify(a.case)
 if a.environment:
  r=httpx.get('http://127.0.0.1:11434/api/ps',timeout=10);r.raise_for_status()
  print(json.dumps([{'name':m['name'],'size_vram':m.get('size_vram'),'context_length':m.get('context_length')} for m in r.json()['models']],ensure_ascii=False))
