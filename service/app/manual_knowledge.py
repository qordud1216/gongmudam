"""Full-page, opt-in system manuals. Separate from entitlement/legal retrieval."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import hashlib,io,json,re,uuid
from fastapi import HTTPException
from . import folders
from .search import BM25

KIND='system_manual'
LIBRARY='esaram-manuals-v68'
MAX_BYTES=64*1024*1024
MAX_PAGES=1000
LEGAL_TERMS=('법령','법적','법정','규정','지급기준','인정기준','상한','한도','며칠','몇일','얼마','몇시간','수당계산','의무','기한','조건','무슨서류','어떤서류','서류는무엇','필요서류','필수서류')

def flat(value):return re.sub(r'\s+','',value).lower()

def extract_pdf(raw):
    """Index every page; preserve exact extraction and page-local offsets."""
    from pypdf import PdfReader
    if len(raw)>MAX_BYTES:raise ValueError('매뉴얼은 64MB 이하 PDF로 등록하세요.')
    reader=PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:raise ValueError('암호 PDF는 해제된 원본을 등록하세요.')
    if not 0<len(reader.pages)<=MAX_PAGES:raise ValueError('매뉴얼은 1~1000쪽 범위로 나눠 등록하세요.')
    units=[];coverage=[]
    for page_number,page in enumerate(reader.pages,1):
        text=page.extract_text() or ''
        coverage.append(dict(page=page_number,characters=len(text),status='indexed' if text.strip() else 'no_text'))
        # An empty/image-only page is recorded explicitly, never called fully searchable.
        if text.strip():units.append(dict(page=page_number,loc=f'PDF {page_number}쪽',text=text))
    return dict(units=units,page_count=len(reader.pages),indexed_pages=sum(p['status']=='indexed' for p in coverage),page_coverage=coverage)

def register_files(paths,progress=None):
    """Local operator entry point, atomic source registration after bounded extraction.

    Exact files must be explicitly supplied. Originals become hash-addressed app-owned
    copies, independent of Downloads and of the folder preview/re-scan pipeline.
    """
    from . import knowledge
    paths=[Path(p) for p in paths]
    if not 1<=len(paths)<=30:raise ValueError('등록할 PDF 1~30개를 지정하세요.')
    destination=folders.DB_PATH.parent/'manuals';destination.mkdir(parents=True,exist_ok=True)
    prepared=[]
    for i,path in enumerate(paths,1):
        folders.roots_checked([str(path.parent)])
        if path.suffix.lower()!='.pdf' or path.is_symlink() or path.is_junction():raise ValueError('일반 PDF 파일만 등록하세요.')
        before=path.stat()
        if before.st_size>MAX_BYTES:raise ValueError('64MB 이하 PDF를 지정하세요.')
        raw=path.read_bytes();after=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('등록 중 원본이 변경됐습니다.')
        parsed=extract_pdf(raw)
        if not parsed['units']:raise ValueError('읽을 수 있는 텍스트가 없습니다. OCR이 필요한 문서입니다.')
        digest=hashlib.sha256(raw).hexdigest();target=destination/(digest+'.pdf')
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('보관 사본이 변경됐습니다. 먼저 확인하세요.')
        else:
            temp=destination/(uuid.uuid4().hex+'.tmp')
            try:temp.write_bytes(raw);temp.replace(target)
            finally:temp.unlink(missing_ok=True)
        record=dict(id='manual-'+digest[:32],library_id=LIBRARY,library_name='e-사람 매뉴얼 · 전체 페이지',file_id=digest[:32],
            title=path.name,path=str(target),sha256=digest,kind='업무편람',institution='e-사람 사용자매뉴얼 · 제공 파일',
            effective_date='',registered_at=folders.stamp(),scan_profile='direct-v63',reference_kind=KIND,system='e-사람',
            local_only=True,limited=parsed['indexed_pages']!=parsed['page_count'],**parsed)
        prepared.append(record)
        if progress:progress(dict(file=i,total_files=len(paths),title=path.name,page_count=parsed['page_count'],indexed_pages=parsed['indexed_pages']))
    folders.initialize();knowledge.initialize()
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT payload FROM libraries WHERE id=?',(LIBRARY,)).fetchone()
        if old:
            lib=json.loads(old['payload'])
            if lib.get('reference_kind')!=KIND:raise ValueError('같은 ID의 다른 자료함이 있습니다.')
        else:
            lib=dict(id=LIBRARY,version=1,name='e-사람 매뉴얼 · 전체 페이지',situation='시스템 사용법 안내 자료',
                reference_kind=KIND,roots=[str(destination)],files={},projects={},warnings=[],history=[],scanned_at=folders.stamp())
        for record in prepared:
            # Full text is only in the knowledge index, never the general folder preview.
            file=dict(id=record['file_id'],path=record['path'],name=record['title'],root=str(destination),size=Path(record['path']).stat().st_size,
                mtime_ns=Path(record['path']).stat().st_mtime_ns,sha256=record['sha256'],units=[],present=True,status=f"전체 {record['indexed_pages']}/{record['page_count']}쪽 색인 · 매뉴얼 검색 사용",
                project_ids=[],suggestions=[],bucket='common',manual=True,confirmed=True,changed=False,review_reason='전체 페이지 매뉴얼 등록',clues=dict(stages=[],evidence=[]),duplicate_count=0,duplicates=[])
            lib['files'][file['id']]=file
            previous=c.execute('SELECT payload FROM knowledge_sources WHERE id=?',(record['id'],)).fetchone()
            if previous:
                original=json.loads(previous['payload']);record['registered_at']=original['registered_at']
            c.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?) ON CONFLICT(library_id,file_id) DO UPDATE SET enabled=1,payload=excluded.payload',
                (record['id'],LIBRARY,record['file_id'],1,folders.encode(record)))
        if old:lib['version']+=1
        lib['history']=(lib.get('history',[])+[dict(at=folders.stamp(),kind='매뉴얼 전체 색인',detail={'files':len(prepared)})])[-1000:]
        c.execute('INSERT INTO libraries VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,payload=excluded.payload',(LIBRARY,lib['version'],folders.encode(lib)))
    return dict(registered=len(prepared),pages=sum(r['page_count'] for r in prepared),indexed_pages=sum(r['indexed_pages'] for r in prepared),
        sources=[{k:r[k] for k in ('id','title','sha256','page_count','indexed_pages','limited')} for r in prepared])

def classify(query):
    q=flat(query)
    explicit=bool(re.search(r'e[-·]?사람|이사람|스마트출장(?:앱|예약)|디브레인|dbrain',q))
    legal=any(t in q for t in LEGAL_TERMS)
    control=any(t in q for t in ('입력','버튼','메뉴','화면','목록','안나','안떠','안보','불러','클릭','변경','취소','상신','결재선','신청방법','신고방법','엑셀','등록','전송','적용','조회','출력','반영','지정'))
    if legal and not control:return None
    if legal and control:
        # Amount/input questions may merely ask where a value is typed.
        input_only=any(t in q for t in ('금액입력','금액을입력','일수를입력')) and not any(t in q for t in LEGAL_TERMS)
        if not input_only:
            if explicit and any(t in q for t in ('방법도','어디서','신청방법','메뉴도')):return dict(kind='mixed',family='',query=query)
            return None
    families=[('overtime',('초과근무','시간외근무')),('flex',('유연근무','시차출퇴근','출퇴근지정')),('duty',('당직',)),('security',('보안점검',)),
        ('lecture',('외부강의','외부강연','겸직')),('leave',('휴가','연가','근무상황','대체휴무','병가','공가')),('travel',('출장','여비','운임','정산','구매카드','기관카드')),('idcard',('공무원증',))]
    family=next((name for name,words in families if any(t in q for t in words)),'')
    implicit=control and any(t in q for t in ('초과근무','유연근무','포상휴가','근무상황','당직','보안점검','결재선'))
    if not explicit and not implicit:return None
    if not control and not any(t in q for t in ('방법','어떻게','사용법','매뉴얼','도움말')):return None
    if family=='travel' and ('스마트' in q or '예약' in q):family='smart'
    if any(t in q for t in ('디브레인','dbrain')):family='dbrain'
    return dict(kind='manual',family=family,query=query)

FAMILY_ANCHORS={
    'overtime':('초과근무','시간외근무'),'flex':('유연근무','출퇴근지정','시차출퇴근'),'duty':('당직',),'security':('보안점검',),
    'leave':('휴가','연가','근무상황','대체휴무'),'lecture':('외부강의','겸직'),'travel':('출장','여비'),
    'smart':('스마트출장','정산내역','예약'),'dbrain':('dbrain','디브레인','지급명세서','지급금액'),'idcard':('공무원증',)}

def retrieve(query,docs,plan):
    """Rank page context, requiring domain and requested action on the same page."""
    q=flat(query);family=plan['family'];anchors=FAMILY_ANCHORS.get(family)
    if not anchors:return []
    failure=any(t in q for t in ('안나','안떠','안보','없어','조회되지','목록이없'))
    operation=[t for t in ('취소','결재선','정산','엑셀','변경','신고','전송','금액조정','계좌') if t in q]
    if any(t in q for t in ('등록','입력','지정')):operation+=['등록','입력','저장','지정','첨부','선택']
    # Specific noun facets prevent the generic document title from matching every page.
    specific=[t for t in ('포상휴가','사후신청','희망저축','연가저축','근무지외','근무지내','외부강의','겸직','지급금액조정','여비계좌','정부구매카드','기관카드','사진','운임','병가','진단서','공가','대체휴무','육아','출산','총량','월별집계','승인내역') if t in q]
    candidates=[]
    for d in docs:
        if d.get('reference_kind')!=KIND or not d['enabled'] or not d['current']:continue
        for u in d['units']:
            t=flat(u['text'])
            if re.search(r'contents|목차',t[:140]):continue
            if '단위업무' in t or '개요' in t[:120]:continue
            if family=='travel' and '정산' in q:
                # The app's product name appears in unrelated application tips.
                # A chapter list is navigation, not the requested operation.
                operation_text=t.replace('스마트출장예약정산앱','').replace('스마트출장예약정산','')
                if '정산' not in operation_text:continue
                if not re.search(r'선택|클릭|입력|조회|등록|저장|불러|연계|확인|신청|전송',operation_text):continue
            # Continuation pages often omit the chapter name; their own manual
            # title can supply that domain, while action/facets must still match.
            domain=t+flat(d['title']) if family in ('overtime','flex','leave','travel','security','duty') else t
            if not any(a in domain for a in anchors):continue
            if specific and not all(a in t for a in specific):continue
            if any(a in q for a in ('서류','첨부')) and not any(a in t for a in ('서류','첨부')):continue
            if operation and not any(a in t for a in operation):continue
            if failure and not any(a in t for a in ('않','없','불가','안되','못','필요','선행')):continue
            candidates.append((d,u))
    if not candidates:return []
    expanded=query+' '+('조회되지 목록 표시되지 선행 작업' if failure else '')
    threshold=-1 if family=='travel' and '정산' in q else 1
    ranked=BM25([u['text'] for _,u in candidates]).top(expanded,k=len(candidates),min_score=threshold)
    values=[]
    for i,score in ranked:
        d,u=candidates[i];t=flat(u['text'])
        if failure and re.search(r'faq|^q',t):score+=12
        if family=='travel' and '출장관리' in d['title']:score+=5
        if family=='travel' and '정산' in q:
            if '정산적용' in t:score+=20
            if '결재신청' in t:score+=8
            if '7.4.1' in t:score+=6
        if family=='smart' and '스마트출장앱' in d['title']:score+=6
        preferred={'overtime':'초과근무','flex':'근무형태','leave':'근무상황','lecture':'근무상황','security':'보안점검','duty':'보안점검'}
        if family in preferred and preferred[family] in d['title']:score+=12
        if not failure and 'faq' in t:score-=10
        values.append((score,d,u))
    values.sort(key=lambda v:v[0],reverse=True)
    result=[]
    for score,d,u in values:
        # Keep complete page context so numbered actions and exceptions stay together.
        result.append(dict(id=f"{d['id']}:page:{u['page']}",source_id=d['id'],library_id=d['library_id'],file_id=d['file_id'],
            title=d['title'],kind=d['kind'],institution=d['institution'],effective_date='',sha256=d['sha256'],limited=d['limited'],
            reference_kind=KIND,page=u['page'],page_count=d['page_count'],indexed_pages=d['indexed_pages'],loc=u['loc'],
            text=u['text'],quote=u['text'],score=round(score,2),official=None))
        if len(result)==3:break
    return result

def respond(query,library_id=None):
    plan=classify(query)
    from . import knowledge
    if plan is None:
        q=flat(query)
        system=bool(re.search(r'e[-·]?사람|이사람|스마트출장|초과근무|유연근무',q))
        if system and any(t in q for t in LEGAL_TERMS) and not knowledge.intent.analyze(query):
            notice='질문은 규정상 요건·기한에 관한 내용이에요. 등록한 법령에서 해당 기준을 확인할 수 없어 매뉴얼의 화면 설명으로 대신 답하지 않습니다. 적용 기관과 해당 규정을 확인해 주세요.'
            tree=dict(kind='unavailable',title='규정 근거를 더 확인해야 해요',branches=[dict(label='확인할 내용',items=[dict(text=notice,ref=None)])],note='e-사람 사용법과 법령 근거를 구분합니다.')
            return dict(query=query,mode='source_unavailable',model=None,profile=None,summary=notice,answer='',notice=notice,plan=None,alternatives=[],cited=[],related=[],personal_notes=[],
                knowledge=dict(evidence=[],experiences=[],excluded=[],mode='source_unavailable',model=None,notice=notice,answer='',reference_kind='legal',scope='등록 법령의 직접 근거 필요',tree=tree))
        return None
    docs=knowledge.sources(library_id)
    if plan['kind']=='mixed':
        notice='규정상 기준과 e-사람 화면 사용법이 함께 들어 있어요. 금액·일수 기준과 화면 조작 중 먼저 확인할 내용을 나눠 질문해 주세요.';hits=[]
    else:
        hits=retrieve(query,docs,plan);notice=''
        if not hits:notice='등록 매뉴얼에서 질문에 직접 답하는 화면·절차를 확인하지 못했어요. 사용 중인 메뉴명과 오류 문구를 알려주세요.'
    scope='제공된 e-사람 매뉴얼의 화면 조작 안내입니다. PDF 쪽수 기준이며 현재 기관 화면과 다를 수 있어요. 법정 지급액·휴가일수는 규정 근거로 별도 확인하세요.'
    if hits:
        # Display the primary page coherently. A line heuristic can retain a
        # section number but omit its action or a wrapped negative/exception.
        display='\n'.join(s for s in hits[0]['text'].splitlines() if not s.strip().startswith('Copyright'))
        tree=dict(kind='manual',title='e-사람 사용법을 원문에서 확인해요',branches=[dict(label=f"절차·주의사항 · PDF {hits[0]['page']}쪽",items=[dict(text=display.strip(),ref=1)]),
            dict(label='함께 찾은 페이지',items=[dict(text=f"{h['title']} · {h['loc']}",ref=i) for i,h in enumerate(hits,1)])],note=scope)
    else:
        tree=dict(kind='unavailable',title='사용할 메뉴를 조금 더 알려주세요',branches=[dict(label='확인할 내용',items=[dict(text=notice,ref=None)])],note=scope)
    answer='\n\n'.join(f"[{i}] {h['loc']}\n{h['text']}" for i,h in enumerate(hits,1))
    reply=dict(evidence=hits,experiences=[],excluded=[],mode='source_manual' if hits else 'source_unavailable',model=None,notice=notice,answer=answer,
        reference_kind=KIND,intent=plan,scope=scope,tree=tree)
    return dict(query=query,mode=reply['mode'],model=None,profile=None,summary='e-사람 사용법 · 등록 매뉴얼 원문' if hits else notice,
        answer=answer,notice=notice,plan=None,alternatives=[],cited=[],related=[],personal_notes=[],knowledge=reply)
