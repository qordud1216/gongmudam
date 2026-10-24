"""여비 원문 감시의 영속 상태. 계산기는 읽기만 하며 네트워크를 호출하지 않는다."""
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone, timedelta
import copy, hashlib, json, sqlite3, uuid

ROOT=Path(__file__).resolve().parents[1]
DB_PATH=ROOT/'data/regulation-monitor.db'
OBJECTS=ROOT/'data/regulation-monitor/objects'

def dumps(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(raw):return hashlib.sha256(raw).hexdigest()
def now():return datetime.now(timezone.utc)
def stamp():return now().isoformat()

@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH,timeout=20);c.row_factory=sqlite3.Row
    try:
        with c:yield c
    finally:c.close()

def initialize():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL DEFAULT 1,interval_hours INTEGER NOT NULL DEFAULT 24,revision INTEGER NOT NULL DEFAULT 1,next_check_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,status TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,lease_until TEXT NOT NULL,result_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS active(id INTEGER PRIMARY KEY CHECK(id=1),base_sha TEXT NOT NULL,pack_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS changes(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL UNIQUE,signature TEXT NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL,detected_at TEXT NOT NULL,last_seen TEXT NOT NULL,detail_json TEXT NOT NULL);
        ''')
        c.execute('INSERT OR IGNORE INTO settings(id,next_check_at) VALUES (1,?)',(stamp(),))

def signature(pack):
    p=copy.deepcopy(pack)
    for key in ('profile','bundle_sha256','version','verified_through','source_review','verification_certificate'):p.pop(key,None)
    for s in p.get('sources',{}).values():
        for key in ('verified_on','review_url'):s.pop(key,None)
    for key in ('reviewed_on','preview_until'):p.get('validity_policy',{}).pop(key,None)
    return sha(dumps(p).encode())

def active_bundle(base_sha):
    if not DB_PATH.is_file():return None
    with db() as c:
        row=c.execute('SELECT * FROM active WHERE id=1').fetchone()
        return json.loads(row['pack_json']) if row and row['base_sha']==base_sha else None

def settings():
    initialize()
    with db() as c:return dict(c.execute('SELECT * FROM settings WHERE id=1').fetchone())

def claim(force=False):
    initialize();t=now();iso=t.isoformat()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        expired=c.execute("SELECT * FROM runs WHERE status='running' AND lease_until<=?",(iso,)).fetchall()
        for row in expired:
            data=json.loads(row['result_json']);data.update(summary='중단된 원문 확인을 다시 예약했습니다.',error='이전 실행이 완료되지 않았습니다.')
            c.execute("UPDATE runs SET status='failed',finished_at=?,result_json=? WHERE id=?",(iso,dumps(data),row['id']))
        current=c.execute("SELECT id FROM runs WHERE status='running' AND lease_until>?",(iso,)).fetchone()
        if current:return current['id'],False
        s=c.execute('SELECT * FROM settings WHERE id=1').fetchone()
        if not force and (not s['enabled'] or s['next_check_at']>iso):return None,False
        # Manual checks are also rate limited; timers/CLI share this durable lease.
        recent=c.execute('SELECT id,started_at FROM runs ORDER BY started_at DESC LIMIT 1').fetchone()
        if force and recent and datetime.fromisoformat(recent['started_at'])>t-timedelta(seconds=60):return recent['id'],False
        key=uuid.uuid4().hex
        c.execute('INSERT INTO runs VALUES (?,?,?,?,?,?)',(key,'running',iso,None,(t+timedelta(minutes=15)).isoformat(),dumps({'summary':'공식 원문과 현행 버전을 확인하고 있습니다.'})))
        return key,True

def run_view(row):return {**dict(row),**json.loads(row['result_json'])}
def runs(limit=20):
    if not DB_PATH.is_file():return []
    with db() as c:return [run_view(r) for r in c.execute('SELECT * FROM runs ORDER BY started_at DESC LIMIT ?',(limit,))]

def store_object(raw):
    digest=sha(raw);OBJECTS.mkdir(parents=True,exist_ok=True);target=OBJECTS/digest
    if target.exists() and sha(target.read_bytes())!=digest:raise ValueError('보존한 원문 증거의 해시가 다릅니다.')
    if not target.exists():
        temp=OBJECTS/(digest+'.'+uuid.uuid4().hex+'.tmp');temp.write_bytes(raw);temp.replace(target)
    return digest

def change_rows():
    if not DB_PATH.is_file():return []
    with db() as c:return [{**dict(r),**json.loads(r['detail_json'])} for r in c.execute('SELECT * FROM changes ORDER BY detected_at DESC')]

def resolved_nonmaterial(item,pack):
    """A review click alone never lifts a hold; retain verifiable equality proof."""
    proof=item.get('resolution',{});targets=item.get('sources',[])
    if item['state']!='reviewed' or proof.get('kind')!='linked_law_scope_v1' or len(targets)!=1:return False
    source=targets[0];baseline=pack['sources'].get('national',{})
    if (item['signature']!=signature(pack) or proof.get('signature')!=item['signature'] or source['source_id']!='national'
        or proof.get('source_id')!='national' or source['old_sha']!=baseline.get('sha256')
        or proof.get('old_sha')!=source['old_sha'] or proof.get('new_sha')!=source['new_sha']):return False
    from . import regulation_sources
    try:
        values=[]
        for digest in (source['old_sha'],source['new_sha']):
            raw=(OBJECTS/digest).read_bytes()
            if sha(raw)!=digest:return False
            values.append(regulation_sources.source_material('national',raw,baseline))
        return values[0]==values[1] and sha(dumps(values[0]).encode())==proof.get('scoped_sha256') and proof.get('current_id')==regulation_sources.baseline_id(baseline,'lsiSeq')
    except (ValueError,OSError,UnicodeError):return False

def holds(pack,trip):
    if not pack or not DB_PATH.is_file():return []
    sig=signature(pack);ids=set(pack['profile']['source_ids']);found=[]
    for item in change_rows():
        if item['signature']!=sig:continue
        if resolved_nonmaterial(item,pack):continue
        for source in item['sources']:
            if source['source_id'] in ids and (not source.get('effective_date') or trip['end_date']>=source['effective_date']):
                found.append(dict(id=item['id'],title=item['title'],state=item['state'],source_id=source['source_id'],
                    message='공식 기준의 변경이 감지되었습니다. 변경 알림함에서 적용 시점과 계산 기준을 검토하세요.'))
                break
    return found

def finish(key,base_sha,pack,result,new_pack=None):
    """인증서·알림·실행 결과를 한 트랜잭션으로 저장. 만료된 실행은 배포 불가."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM runs WHERE id=?',(key,)).fetchone()
        if not row or row['status']!='running' or row['lease_until']<=stamp():raise ValueError('실행 잠금이 만료되었습니다. 다시 확인하세요.')
        sources=result.get('changes',[])
        if sources:
            fingerprint=sha(dumps({'signature':signature(pack),'sources':[(s['source_id'],s.get('current_version'),s['new_sha']) for s in sources]}).encode())
            existing=c.execute('SELECT id FROM changes WHERE fingerprint=?',(fingerprint,)).fetchone()
            if existing:c.execute('UPDATE changes SET last_seen=? WHERE id=?',(stamp(),existing['id']))
            else:
                d=dict(title='출장 기준 변경 · 담당자 검토 필요',summary=f"공식 자료 {len(sources)}종에서 차이를 발견했습니다. 자동 갱신을 보류했습니다.",sources=sources,run_id=key,history=[],notice='시행일을 확정하지 못한 변경은 해당 근거를 쓰는 모든 출장을 영향 가능 대상으로 표시합니다. 확인 기록은 새 지급 기준의 승인·배포가 아닙니다. 원문·시행일·금액표와 계산식을 별도 검증해야 합니다.')
                c.execute('INSERT INTO changes VALUES (?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,fingerprint,signature(pack),'pending',1,stamp(),stamp(),dumps(d)))
        # Reassess only independently reproducible false positives, with a full
        # successful source check and optimistic revision guard in this lease.
        from . import regulation_sources
        pending=[{**dict(r),**json.loads(r['detail_json'])} for r in c.execute('SELECT * FROM changes WHERE signature=?',(signature(pack),))]
        allowed=regulation_sources.nonmaterial_reviews(pack,pending,result) if result.get('status')=='unchanged' else []
        requested=result.get('nonmaterial_reviews',[]);resolved=[]
        for proof in allowed:
            if proof not in requested:continue
            item=next(x for x in pending if x['id']==proof['id'])
            d=json.loads(item['detail_json'])
            d['resolution']={**proof,'at':stamp(),'run_id':key,'manifest_sha256':result['manifest_sha256']}
            d['history'].append(dict(at=stamp(),action='nonmaterial_verified',reason='공식 원문 9종·현행 연결 대조 완료. 공무원 여비 규정의 고유 본문·버전·첨부가 동일하고 차이는 연계 화면의 다른 문서에 한정됨을 보존 원문으로 재현했습니다. 새 기준 승인이나 금액 변경이 아닙니다.',proof=d['resolution']))
            d['summary']='다른 법령의 머리말 변경으로 확인했습니다. 여비 기준은 동일하며 오탐 보류를 해제했습니다.'
            d['notice']='원래 감지 내용과 원문 해시·검토 이력을 보존합니다. 새 지급 기준을 승인한 기록이 아닙니다.'
            c.execute("UPDATE changes SET state='reviewed',revision=revision+1,detail_json=? WHERE id=? AND revision=?",(dumps(d),item['id'],item['revision']))
            item.update(d,state='reviewed');resolved.append(item['id'])
        if resolved:result['resolved_nonmaterial']=resolved
        # Genuine differences still prevent renewal even after acknowledgement or upstream rollback.
        blocked=any(not resolved_nonmaterial(item,pack) for item in pending)
        if new_pack and signature(new_pack)!=signature(pack):raise ValueError('기간 갱신 과정에서 계산 기준이 달라졌습니다.')
        if new_pack and not blocked:
            c.execute('INSERT OR REPLACE INTO active VALUES (1,?,?)',(base_sha,dumps(new_pack)))
        elif new_pack and blocked:
            result.update(status='changed',summary='기존에 발견한 변경을 검토하고 새 기준을 검증하기 전까지 확인 기간을 늘리지 않습니다.')
        status=result['status'];hours=c.execute('SELECT interval_hours FROM settings WHERE id=1').fetchone()[0]
        c.execute('UPDATE runs SET status=?,finished_at=?,result_json=? WHERE id=?',(status,stamp(),dumps(result),key))
        c.execute('UPDATE settings SET next_check_at=? WHERE id=1',((now()+timedelta(hours=1 if status=='failed' or result.get('errors') else hours)).isoformat(),))
    return result
