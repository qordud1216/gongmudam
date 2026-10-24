"""폴더 자료함: 명시한 로컬 폴더만 읽고, 근거가 있는 업무 묶음을 제안한다."""
from __future__ import annotations
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime,timezone,date
import copy,hashlib,io,json,os,re,sqlite3,stat,tempfile,uuid,zipfile
from fastapi import APIRouter,HTTPException
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field
from . import parsers

DB_PATH=Path(__file__).resolve().parent.parent/'data'/'folders.db'
router=APIRouter(prefix='/api/folders',tags=['여러 폴더·업무 묶음'])
MAX_FILES=300;MAX_ENTRIES=5000;MAX_BYTES=5*1024*1024;TOTAL_BYTES=40*1024*1024
SKIP={'.git','.venv','node_modules','__pycache__','$recycle.bin','system volume information'}
STAGES=[('계획·요청',('계획','요청','안내')),('회신·취합',('회신','명단','신청','참석자')),('실행·증빙',('견적','영수증','증빙','실시')),('결과·보고',('결과','보고','정산'))]
def stamp():return datetime.now(timezone.utc).isoformat()
def encode(v):return json.dumps(v,ensure_ascii=False)
class Strict(BaseModel):model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class Connect(Strict):
    name:str=Field(min_length=2,max_length=100)
    roots:list[str]=Field(min_length=1,max_length=10)
    situation:str=Field(default='',max_length=3000)
class Version(Strict):version:int=Field(ge=1)
class Scan(Version):roots:list[str]|None=Field(default=None,min_length=1,max_length=10)
class Assign(Version):
    project_ids:list[str]=Field(default_factory=list,max_length=20)
    bucket:str=Field(default='review',pattern='^(review|common)$')
    reason:str=Field(min_length=5,max_length=500)
class Project(Version):name:str=Field(min_length=2,max_length=150)
class Link(Version):job_id:str=Field(min_length=1,max_length=40)
@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(DB_PATH,timeout=20);c.row_factory=sqlite3.Row
    try:
        with c:yield c
    finally:c.close()
def initialize():
    with db() as c:c.execute('CREATE TABLE IF NOT EXISTS libraries(id TEXT PRIMARY KEY,version INTEGER NOT NULL,payload TEXT NOT NULL)')
def get(c,key):
    r=c.execute('SELECT * FROM libraries WHERE id=?',(key,)).fetchone()
    if not r:raise HTTPException(404,'자료함이 없습니다.')
    return json.loads(r['payload'])|{'id':key,'version':r['version']}
def save(c,v,version,kind,detail):
    current=get(c,v['id'])
    if current['version']!=version:raise HTTPException(409,'다른 변경이 있습니다. 자료함을 새로 열어 주세요.')
    v['version']=version+1;v['history']=(v.get('history',[])+[{'at':stamp(),'kind':kind,'detail':detail}])[-1000:]
    c.execute('UPDATE libraries SET version=?,payload=? WHERE id=?',(v['version'],encode(v),v['id']))
    return present(v)
def path_key(p):return os.path.normcase(str(p))
def roots_checked(values):
    result=[]
    for value in values:
        p=Path(value)
        if not p.is_absolute() or str(p).startswith(('\\\\','//')):raise HTTPException(422,'절대 경로의 로컬 폴더를 입력하세요. 네트워크 경로는 현재 지원하지 않습니다.')
        try:
            if any(q.is_symlink() or q.is_junction() for q in (p,*p.parents)):raise HTTPException(422,'연결점·심볼릭 링크 폴더는 직접 연결하지 않습니다.')
            p=p.resolve(strict=True)
            if not p.is_dir() or p==Path(p.anchor):raise HTTPException(422,'드라이브 전체 대신 업무 하위 폴더를 지정하세요.')
            # 상위 경로의 연결점도 폴더 경계를 우회할 수 있으므로 제외한다.
            if any(a.is_symlink() or a.is_junction() for a in p.parents):raise HTTPException(422,'연결점이 포함된 경로는 지원하지 않습니다.')
        except OSError as exc:raise HTTPException(422,'읽을 수 있는 업무 폴더 경로를 확인하세요.') from exc
        if path_key(p) not in {path_key(q) for q in result}:result.append(p)
    return result

def extract(path,raw):
    ext=path.suffix.lower();units=[];limited=False
    if ext not in {'.txt','.md','.csv','.xlsx','.docx','.hwpx','.pdf'}:return [],'본문 미지원 · 파일명만 확인',False
    if ext in {'.xlsx','.docx','.hwpx'}:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if len(z.infolist())>512 or sum(e.file_size for e in z.infolist())>20*1024*1024:raise ValueError('압축 해제 제한 초과')
            if any('externalLinks/' in e.filename or 'vbaProject' in e.filename for e in z.infolist()):raise ValueError('매크로·외부 연결 제외')
    if ext=='.xlsx':
        from openpyxl import load_workbook
        wb=load_workbook(io.BytesIO(raw),read_only=True,data_only=False,keep_links=False)
        try:
            limited=len(wb.worksheets)>5
            for ws in wb.worksheets[:5]:
                limited=limited or ws.max_row>200 or ws.max_column>30
                header=[]
                for n,row in enumerate(ws.iter_rows(max_row=min(ws.max_row,200),max_col=min(ws.max_column,30)),1):
                    values=[str(c.value)[:1000] if c.value is not None and c.data_type!='f' else '' for c in row]
                    labels={'행사명','업무명','사업명','교육명','연도','사업연도','개최일','행사일','교육일','주관부서','주관기관'}
                    text=' / '.join(v for v in values if v)
                    if len(values)>1 and values[0].rstrip(':：').strip() in labels and values[1] and values[1] not in labels:
                        text=values[0].rstrip(':：')+': '+values[1]+' / '+' / '.join(values[2:])
                    elif header:
                        text=' / '.join(f'{h}: {value}' for h,value in zip(header,values) if h in labels and value) or text
                    if sum(v in labels for v in values)>1:header=values
                    if text:units.append({'text':text[:2000],'loc':f'{ws.title} {n}행'})
        finally:wb.close()
    elif ext=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw));limited=len(reader.pages)>20
        for n,page in enumerate(reader.pages[:20],1):
            for line in (page.extract_text() or '').splitlines():
                if line.strip():units.append({'text':line.strip()[:2000],'loc':f'{n}쪽'})
    elif ext in {'.txt','.md','.csv'}:
        value=None
        for enc in ('utf-8-sig','cp949'):
            try:value=raw.decode(enc);break
            except UnicodeDecodeError:pass
        value=value if value is not None else raw.decode('utf-8',errors='replace')
        units=[{'text':line.strip()[:2000],'loc':f'{n}행'} for n,line in enumerate(value.splitlines(),1) if line.strip()]
    else:
        # 기존 문서 파서 재사용. 압축 해제 제한을 먼저 검사한다.
        with tempfile.TemporaryDirectory(prefix='seomu-folder-') as directory:
            snapshot=Path(directory)/('source'+ext);snapshot.write_bytes(raw);units=parsers.parse_file(snapshot)
    limited=limited or len(units)>256
    return [{'text':u['text'][:2000],'loc':u['loc']} for u in units[:256]],('본문 일부 확인' if limited else '본문 확인' if units else '추출 본문 없음 · 파일명만 확인'),limited

def norm(v):return re.sub(r'[\W_]+','',v).casefold()
def clues(name,units):
    evidence=[];titles=[];years=set();dates=set();organizers=set()
    # 파일명·폴더명 유사도만으로 자동으로 같은 행사라고 결정하지 않는다.
    for u in units:
        line=u['text']
        for label,target in [('행사명',titles),('업무명',titles),('사업명',titles),('교육명',titles)]:
            for m in re.finditer(r'(?:^|[ /|])'+label+r'\s*[:：]\s*([^\n/|]{2,120})',line):
                value=m.group(1).strip();target.append(value);evidence.append({'kind':'업무명','value':value,**u})
        for m in re.finditer(r'(?:연도|사업연도)\s*[:：]\s*((?:19|20)\d{2})',line):years.add(m.group(1));evidence.append({'kind':'연도','value':m.group(1),**u})
        for m in re.finditer(r'(?:개최일|행사일|교육일)\s*[:：]\s*((?:19|20)\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})',line):
            try:d=date(*map(int,m.groups())).isoformat()
            except ValueError:continue
            dates.add(d);years.add(d[:4]);evidence.append({'kind':'개최일','value':d,**u})
        for m in re.finditer(r'(?:주관부서|주관기관)\s*[:：]\s*([^\n/|]{2,80})',line):organizers.add(m.group(1).strip());evidence.append({'kind':'주관','value':m.group(1).strip(),**u})
    unique={norm(t):t for t in titles}
    for title in titles:
        years.update(re.findall(r'(?:19|20)\d{2}',title))
    if not years:
        found=set(re.findall(r'(?:19|20)\d{2}',name))
        if len(found)==1:years=found;evidence.append({'kind':'연도','value':next(iter(found)),'loc':'파일명','text':name})
    common=bool(re.search(r'공통|표준서식|공용',name)) and not unique
    stage=[]
    for label,tokens in STAGES:
        token=next((token for token in tokens if token in name),None)
        if token:stage.append({'stage':label,'loc':'파일명','text':name,'token':token})
    title=next(iter(unique.values())) if len(unique)==1 else None
    valid=title and len(years)==1 and len(dates)<=1 and len(organizers)<=1
    return {'title':title,'year':next(iter(years)) if len(years)==1 else None,'date':next(iter(dates)) if len(dates)==1 else '',
            'organizer':next(iter(organizers)) if len(organizers)==1 else '', 'eligible':bool(valid),'common':common,
            'evidence':evidence[:30],'stages':stage,
            'reason':'문서의 업무명과 연도 일치 여부로 제안' if valid else '여러 업무명·연도·개최일이 섞임' if len(unique)>1 or len(years)>1 or len(dates)>1 or len(organizers)>1 else '공통 자료 후보' if common else '업무명 또는 연도 근거 부족 · 확인 필요'}

def collect(roots):
    files={};warnings=[];count=0;total=0;seen=set();truncated=False
    for root in roots:
        stack=[(root,0)]
        while stack and not truncated:
            directory,depth=stack.pop()
            try:entries=sorted(directory.iterdir(),key=lambda p:p.name.casefold())
            except OSError:warnings.append(f'폴더 읽기 실패: {directory}');continue
            for p in entries:
                count+=1
                if count>MAX_ENTRIES:truncated=True;warnings.append('탐색 항목 5,000개 제한 · 전체 분석 아님');break
                try:
                    if p.is_symlink() or p.is_junction() or p.name.startswith('.') or p.name.casefold() in SKIP:continue
                    st=p.stat()
                    if getattr(st,'st_file_attributes',0)&(getattr(stat,'FILE_ATTRIBUTE_HIDDEN',2)|getattr(stat,'FILE_ATTRIBUTE_SYSTEM',4)):continue
                    if getattr(st,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):continue
                    if p.is_dir():
                        if depth<8:stack.append((p,depth+1))
                        else:warnings.append(f'하위 8단계 제한: {p}')
                        continue
                    if not p.is_file() or path_key(p) in seen:continue
                    if len(files)>=MAX_FILES:truncated=True;warnings.append('파일 300개 제한 · 전체 분석 아님');break
                    seen.add(path_key(p));fid=uuid.uuid5(uuid.NAMESPACE_URL,path_key(p)).hex
                    item={'id':fid,'path':str(p),'name':p.name,'root':str(root),'size':st.st_size,'mtime_ns':st.st_mtime_ns,'sha256':'','units':[],'present':True,'status':''}
                    if st.st_size>MAX_BYTES or total+st.st_size>TOTAL_BYTES:item['status']='읽기 용량 제한 · 본문 미확인'
                    else:
                        # 링크 교체·파일 변동은 저장 전 다시 확인한다.
                        before=p.resolve(strict=True)
                        if not before.is_relative_to(root) or p.is_symlink() or p.is_junction():continue
                        with p.open('rb') as f:raw=f.read(MAX_BYTES+1)
                        after=p.stat()
                        if len(raw)>MAX_BYTES or (after.st_size,after.st_mtime_ns)!=(st.st_size,st.st_mtime_ns):raise ValueError('분석 중 파일 변경 · 재분석 필요')
                        total+=len(raw);item['sha256']=hashlib.sha256(raw).hexdigest()
                        try:item['units'],item['status'],item['limited']=extract(p,raw)
                        except Exception:item['status']='본문 읽기 실패 · 암호·형식·손상·용량 확인'
                    item['clues']=clues(p.name,item['units']);files[fid]=item
                except (OSError,ValueError):warnings.append(f'읽기 실패 또는 변경 중: {p}')
    return files,warnings

def propose(v,incoming,warnings,*,inventory_complete=True):
    oldfiles=v.get('files',{});projects=v.setdefault('projects',{})
    # A portable restore retains registered file IDs. collect() derives a new ID
    # from the installation path, so reuse a prior ID only when the absolute path
    # matches. Sort all candidates to make duplicate legacy paths deterministic.
    old_by_path={}
    for old_id,old in sorted(oldfiles.items()):
        if old.get('path'):
            old_by_path.setdefault(path_key(Path(old['path'])),[]).append(old_id)
    incoming_ids=set(incoming);used_ids=set();remapped={}
    for fid,f in sorted(incoming.items()):
        candidates=old_by_path.get(path_key(Path(f['path'])),[])
        target=next((old_id for old_id in candidates
                     if old_id not in used_ids and (old_id==fid or old_id not in incoming_ids)),fid)
        if target in used_ids:target=fid
        used_ids.add(target)
        f['id']=target
        remapped[target]=f
    incoming.clear();incoming.update(remapped)
    # 같은 이름·연도라도 날짜나 주관이 충돌하면 따로 두고, 근거 없는 파일은 확인함에 둔다.
    identities={}
    for f in incoming.values():
        c=f['clues']
        if c['eligible']:identities.setdefault((norm(c['title']),c['year']),set()).add((c['date'],norm(c['organizer'])))
    for fid,f in incoming.items():
        f['scan_unverified']=False
        c=f['clues'];suggestions=[]
        if c['eligible']:
            variants=identities[norm(c['title']),c['year']]
            complete={(d,o) for d,o in variants if d or o}
            matching={(d,o) for d,o in complete if (not c['date'] or not d or c['date']==d) and (not c['organizer'] or not o or norm(c['organizer'])==o)}
            chosen=next(iter(matching)) if len(matching)==1 else (c['date'],norm(c['organizer']))
            ambiguous=not c['date'] and not c['organizer'] and len(complete)>1
            # 일부 식별자만 있고 후보가 둘 이상이면 배정하지 않는다.
            ambiguous=ambiguous or len(matching)>1
            if not ambiguous:
                identity=encode([norm(c['title']),c['year'],*chosen]);pid=uuid.uuid5(uuid.NAMESPACE_URL,identity).hex
                projects.setdefault(pid,{'id':pid,'name':f"{c['year']} {c['title']}"+(f' · {chosen[0]}' if chosen[0] else ''),'confirmed':False,'identity':identity,'links':[]})
                suggestions=[pid]
            else:c['reason']='같은 업무명에 여러 개최일·주관 후보 · 확인 필요'
        old=oldfiles.get(fid);changed=bool(old and (old['sha256']!=f['sha256'] or old['size']!=f['size'] or old['mtime_ns']!=f['mtime_ns']))
        f.update({'suggestions':suggestions,'project_ids':suggestions,'bucket':'common' if c['common'] else 'review','manual':False,'confirmed':False,'changed':changed,'review_reason':''})
        if old:
            # 사용자 분류를 보존한다. 변경되거나 제안이 달라지면 확인을 다시 요청한다.
            if old.get('manual') or old.get('confirmed'):
                f.update({k:old[k] for k in ('project_ids','bucket','manual','review_reason')})
            if old.get('ai_assignment'):f['ai_assignment']=old['ai_assignment']
            f['content_changed']=bool(changed or old.get('content_changed'))
            f['confirmed']=bool(old.get('confirmed') and not changed and old.get('suggestions')==suggestions)
            if old.get('confirmed') and f['project_ids']==old.get('project_ids') and not changed and old.get('suggestions')==suggestions:f['confirmed']=True
        if old and (old.get('manual') or old.get('confirmed')):f['confirmed']=old.get('confirmed',False)
        incoming[fid]=f
    for fid,old in oldfiles.items():
        if fid not in incoming:
            incoming[fid]=(copy.deepcopy(old)|{'scan_unverified':True,'status':'이번 탐색 미확인 · 이전 자료·분류 보존'}) if not inventory_complete else old|{'present':False,'confirmed':False,'status':'이번 분석에서 확인되지 않음 · 삭제 여부 단정 안 함'}
    hashes={}
    for f in incoming.values():
        if f['present'] and f['sha256']:hashes.setdefault(f['sha256'],[]).append(f['id'])
    for f in incoming.values():
        group=hashes.get(f['sha256'],[]) if f['present'] else []
        f['duplicate_count']=max(0,len(group)-1)
        f['duplicates']=[i for i in group[:101] if i!=f['id']][:100]
    v.update(files=incoming,warnings=warnings,scanned_at=stamp());return v

def present(v):
    result=json.loads(encode(v));files=list(result.pop('files').values());projects=list(result.pop('projects').values())
    for p in projects:
        members=[f for f in files if f['present'] and p['id'] in f['project_ids']]
        if p.get('ai_note'):
            p['ai_note']['stale']=p['ai_note']['membership']!={f['id']:f['sha256'] for f in members}
        p['files']=len(members);p['needs_review']=sum(not f['confirmed'] for f in members)
        p['stages']=[{'name':label,'files':[f['id'] for f in members if any(s['stage']==label for s in f['clues']['stages']) or any(any(token in e['quote'] for token in tokens) for e in f.get('ai_assignment',{}).get('evidence',[]) if e.get('sha256')==f['sha256'])]} for label,tokens in STAGES]
        p['next_actions']=['관련 자료의 내용·결재·실제 처리 여부를 확인하세요.']
        missing=[s['name'] for s in p['stages'] if not s['files']]
        if missing:p['next_actions'].append('자료가 발견되지 않은 단계: '+', '.join(missing)+' · 미처리로 확정하지 않습니다.')
    result.update(files=files,projects=projects,summary={'files':sum(f['present'] for f in files),'projects':sum(p['files']>0 for p in projects),'review':sum(f['present'] and not f['confirmed'] for f in files),'common':sum(f['present'] and (f['bucket']=='common' or len(f['project_ids'])>1) for f in files),'missing':sum(not f['present'] for f in files)})
    return result

@router.get('/libraries')
def libraries():
    with db() as c:return [dict(id=r['id'],version=r['version'],name=json.loads(r['payload'])['name']) for r in c.execute('SELECT * FROM libraries ORDER BY rowid DESC')]
@router.post('/libraries',status_code=201)
def connect(body:Connect):
    roots=roots_checked(body.roots);files,warnings=collect(roots);key=uuid.uuid4().hex
    v=propose({'id':key,'version':1,'name':body.name,'situation':body.situation,'roots':[str(p) for p in roots],'history':[{'at':stamp(),'kind':'폴더 연결·분석','detail':{'roots':[str(p) for p in roots]}}]},files,warnings)
    with db() as c:c.execute('INSERT INTO libraries VALUES(?,?,?)',(key,1,encode(v)))
    return present(v)
@router.get('/libraries/{key}')
def detail(key:str):
    with db() as c:return present(get(c,key))
@router.post('/libraries/{key}/scan')
def scan(key:str,body:Scan):
    with db() as c:v=get(c,key)
    if v['version']!=body.version:raise HTTPException(409,'다른 변경이 있습니다. 자료함을 새로 열어 주세요.')
    if v.get('reference_kind')=='system_manual':raise HTTPException(422,'전체 페이지 매뉴얼은 전용 등록 도구로 다시 색인하세요. 폴더 미리보기로 바꾸지 않습니다.')
    roots=roots_checked(body.roots or v['roots']);files,warnings=collect(roots);v['roots']=[str(p) for p in roots];v=propose(v,files,warnings)
    with db() as c:
        c.execute('BEGIN IMMEDIATE');return save(c,v,body.version,'폴더 재분석',{'roots':v['roots'],'warnings':warnings})
@router.patch('/libraries/{key}/files/{fid}')
def assign(key:str,fid:str,body:Assign):
    with db() as c:
        c.execute('BEGIN IMMEDIATE');v=get(c,key)
        if fid not in v['files']:raise HTTPException(404,'등록 파일이 없습니다.')
        if any(p not in v['projects'] for p in body.project_ids):raise HTTPException(422,'업무 묶음을 확인하세요.')
        f=v['files'][fid]
        if not f['present']:raise HTTPException(422,'현재 확인되지 않은 파일입니다. 폴더를 다시 분석하세요.')
        f.update(project_ids=list(dict.fromkeys(body.project_ids)),bucket=body.bucket,manual=True,confirmed=True,changed=False,review_reason=body.reason)
        return save(c,v,body.version,'파일 분류 확인',{'file_id':fid,'project_ids':f['project_ids'],'bucket':f['bucket'],'reason':body.reason})
@router.post('/libraries/{key}/projects',status_code=201)
def create_project(key:str,body:Project):
    with db() as c:
        c.execute('BEGIN IMMEDIATE');v=get(c,key);pid=uuid.uuid4().hex
        v['projects'][pid]={'id':pid,'name':body.name,'confirmed':True,'identity':'manual','links':[]}
        return save(c,v,body.version,'업무 묶음 추가',{'project_id':pid,'name':body.name})
@router.patch('/libraries/{key}/projects/{pid}')
def rename(key:str,pid:str,body:Project):
    with db() as c:
        c.execute('BEGIN IMMEDIATE');v=get(c,key)
        if pid not in v['projects']:raise HTTPException(404,'업무 묶음이 없습니다.')
        v['projects'][pid]['name']=body.name
        return save(c,v,body.version,'묶음 이름 변경',{'project_id':pid,'name':body.name})
@router.post('/libraries/{key}/projects/{pid}/confirm')
def confirm(key:str,pid:str,body:Version):
    with db() as c:
        c.execute('BEGIN IMMEDIATE');v=get(c,key)
        if pid not in v['projects']:raise HTTPException(404,'업무 묶음이 없습니다.')
        v['projects'][pid]['confirmed']=True
        for f in v['files'].values():
            if pid in f['project_ids'] and f['present']:f.update(manual=True,confirmed=True,changed=False)
        return save(c,v,body.version,'업무 묶음 분류 확인',{'project_id':pid,'note':'업무 완료 확인과 구분'})
@router.post('/libraries/{key}/projects/{pid}/links')
def link(key:str,pid:str,body:Link):
    from . import adhoc
    with adhoc.db() as a:j=adhoc.job(a,body.job_id)
    with db() as c:
        c.execute('BEGIN IMMEDIATE');v=get(c,key)
        if pid not in v['projects']:raise HTTPException(404,'업무 묶음이 없습니다.')
        links=v['projects'][pid]['links']
        if not any(x['job_id']==body.job_id for x in links):links.append({'job_id':body.job_id,'title':j['settings']['title'],'url':'/adhoc.html#job-'+body.job_id})
        return save(c,v,body.version,'자료 취합 업무 연결',{'project_id':pid,'job_id':body.job_id})
@router.get('/libraries/{key}/report.json')
def report(key:str):
    with db() as c:v=present(get(c,key))
    return Response(encode(v),media_type='application/json',headers={'Content-Disposition':'attachment; filename="folder-workspace-report.json"','Cache-Control':'no-store'})
