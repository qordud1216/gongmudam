"""Restore bundled knowledge into a new installation; rebase only package-owned paths."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_path(root, name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or any(x in ('..', '') for x in p.parts) or ':' in name or '\\' in name:
        raise ValueError('Invalid package-relative path')
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('Package path escapes installation')
    return target


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def checked_bundle(root):
    raw = (root / 'submission-data/knowledge.json').read_bytes()
    bundle = json.loads(raw)
    if bundle.get('format') != 1 or not bundle.get('sources'):
        raise ValueError('Unsupported or empty knowledge bundle')
    seen = set()
    for item in bundle['sources']:
        if item['id'] in seen:
            raise ValueError('Duplicate source ID')
        seen.add(item['id'])
        if sha(safe_path(root, item['asset']).read_bytes()) != item['sha256']:
            raise ValueError('Source hash mismatch: ' + item['id'])
        if item.get('reference_kind')=='system_manual':
            if not re.fullmatch(r'[0-9a-f]{64}',item['sha256']) or item['asset']!=f"submission-data/manuals/{item['sha256']}.pdf":
                raise ValueError('Invalid manual asset path')
            pages=item.get('page_count');indexed=item.get('indexed_pages');coverage=item.get('page_coverage',[])
            if type(pages) is not int or not 1<=pages<=1000 or type(indexed) is not int:
                raise ValueError('Invalid manual page count')
            if len(coverage)!=pages or [p.get('page') for p in coverage]!=list(range(1,pages+1)):
                raise ValueError('Incomplete manual page coverage')
            readable={p['page'] for p in coverage if p.get('status')=='indexed'}
            unit_pages=[u.get('page') for u in item['units']]
            if indexed!=len(readable) or set(unit_pages)!=readable or len(unit_pages)!=len(readable) or any(not u.get('text','').strip() for u in item['units']):
                raise ValueError('Manual text/page metadata mismatch')
    monitor = bundle.get('regulation_snapshot')
    if monitor:
        snapshot = safe_path(root, monitor['asset']).read_bytes()
        if sha(snapshot) != monitor['sha256']:
            raise ValueError('Regulation snapshot hash mismatch')
        active = json.loads(snapshot).get('active')
        if active and sha((root/'app/rulepacks/domestic_reviewed_2026_10.json').read_bytes()) != active['base_sha']:
            raise ValueError('Regulation certificate does not match base rules')
        for item in bundle.get('regulation_objects',[]):
            if sha(safe_path(root,item['asset']).read_bytes())!=item['sha256']:
                raise ValueError('Regulation evidence object hash mismatch')
    return bundle, sha(raw)


def manual_copy(root,entry,previous):
    """Restore verified originals inside the app-owned manual endpoint boundary."""
    source=safe_path(root,entry['asset'])
    target=safe_path(root,f"data/manuals/{entry['sha256']}.pdf")
    if target.exists():
        if sha(target.read_bytes())!=entry['sha256']:raise ValueError('Installed manual was changed; refusing to overwrite it')
    else:
        if previous:raise ValueError('Installed manual is missing; refusing to recreate it silently')
        target.parent.mkdir(parents=True,exist_ok=True)
        fd,temp=tempfile.mkstemp(dir=target.parent,suffix='.tmp')
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(source.read_bytes())
            os.replace(temp,target)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    return target


def install_knowledge(root, bundle, previous=None):
    # App modules are deliberately imported only after the caller selected its installation.
    sys.path.insert(0, str(root))
    from app import folders
    target = root / 'data/folders.db'
    first = previous is None
    if first and target.exists():
        raise ValueError('Existing unowned folders.db; restore into an empty installation')
    staged = target.with_suffix('.restore.tmp') if first else target
    if first and staged.exists():
        raise ValueError('Interrupted restore temporary file requires inspection')
    c = sqlite3.connect(staged)
    try:
        if first:
            c.executescript('''
            CREATE TABLE libraries(id TEXT PRIMARY KEY,version INTEGER NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE knowledge_sources(id TEXT PRIMARY KEY,library_id TEXT,file_id TEXT,enabled INTEGER,payload TEXT,UNIQUE(library_id,file_id));
            CREATE TABLE work_experiences(id TEXT PRIMARY KEY,library_id TEXT,payload TEXT);
            ''')
        with c:
            groups = {}
            bundled_ids={e['id'] for e in bundle['sources']}
            bundled_libraries={e['library_id'] for e in bundle['sources']}
            if previous:
                old_root=Path(previous['root'])
                def move_path(value):
                    p=Path(value)
                    return str(root/p.relative_to(old_root)) if p.is_relative_to(old_root) else value
                # Added registrations and new libraries are user data: relocate paths, preserve everything else.
                for sid,payload in c.execute('SELECT id,payload FROM knowledge_sources').fetchall():
                    if sid in bundled_ids:continue
                    value=json.loads(payload)
                    value['path']=move_path(value['path'])
                    c.execute('UPDATE knowledge_sources SET payload=? WHERE id=?',(json.dumps(value,ensure_ascii=False),sid))
                for lid,payload in c.execute('SELECT id,payload FROM libraries').fetchall():
                    if lid in bundled_libraries:continue
                    value=json.loads(payload)
                    value['roots']=[move_path(p) for p in value['roots']]
                    for f in value['files'].values():
                        for field in ('path','root'):
                            if f.get(field):f[field]=move_path(f[field])
                    c.execute('UPDATE libraries SET payload=? WHERE id=?',(json.dumps(value,ensure_ascii=False),lid))
            for entry in bundle['sources']:
                entry = dict(entry)
                asset = entry.pop('asset')
                enabled = entry.pop('enabled')
                path = manual_copy(root,entry|{'asset':asset},previous) if entry.get('reference_kind')=='system_manual' else safe_path(root, asset)
                entry['path'] = str(path)
                key = entry['library_id']
                if first:
                    c.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?)',
                              (entry['id'], key, entry['file_id'], enabled, json.dumps(entry, ensure_ascii=False)))
                else:
                    row = c.execute('SELECT payload FROM knowledge_sources WHERE id=?', (entry['id'],)).fetchone()
                    if not row:
                        raise ValueError('Installed source was removed; refusing to recreate it silently')
                    current = json.loads(row[0])
                    if current['sha256'] != entry['sha256'] or current['file_id'] != entry['file_id']:
                        raise ValueError('Installed source changed; refusing to replace it')
                    current['path'] = str(path)
                    c.execute('UPDATE knowledge_sources SET payload=? WHERE id=?',
                              (json.dumps(current, ensure_ascii=False), entry['id']))
                groups.setdefault(key, []).append(entry)
            for key, entries in groups.items():
                if first:
                    v = dict(id=key, version=1, name=entries[0]['library_name'], roots=[], files={}, projects={},
                             history=[dict(at=datetime.now(timezone.utc).isoformat(), kind='제출 자료 복원', detail={'sources':len(entries)})], warnings=[])
                    if entries[0].get('reference_kind')=='system_manual':v['reference_kind']='system_manual'
                else:
                    row = c.execute('SELECT payload FROM libraries WHERE id=?', (key,)).fetchone()
                    if not row:
                        raise ValueError('Installed library was removed')
                    v = json.loads(row[0])
                roots = set()
                for entry in entries:
                    p = Path(entry['path'])
                    roots.add(str(p.parent))
                    fid = entry['file_id']
                    if first:
                        manual=entry.get('reference_kind')=='system_manual'
                        v['files'][fid] = dict(id=fid, name=entry['title'] if manual else entry.get('official',{}).get('filename',p.name),
                            units=[] if manual else entry['units'], sha256=entry['sha256'], present=True, status=f"전체 {entry['indexed_pages']}/{entry['page_count']}쪽 색인 · 매뉴얼 검색 사용" if manual else '본문 확인',
                            limited=entry['limited'], clues=folders.clues(entry['title'],[] if manual else entry['units']),
                            suggestions=[], project_ids=[], bucket='common', manual=True, confirmed=True,
                            changed=False, review_reason='전체 페이지 매뉴얼 사본' if manual else '등록 법령·지침의 검증된 사본')
                    f = v['files'].get(fid)
                    if f is None:
                        raise ValueError('Installed library file was removed')
                    f.update(path=str(p), root=str(p.parent), size=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns)
                # New user-added roots are preserved; package-owned roots alone are rebased.
                old_root = Path(previous['root']) if previous else None
                def rebased(value):
                    p=Path(value)
                    return str(root/p.relative_to(old_root)) if old_root and p.is_relative_to(old_root) else value
                owned = {str(old_root/Path(e['path']).relative_to(root).parent) for e in entries} if old_root else set()
                extras = [rebased(r) for r in v['roots'] if r not in owned]
                for fid,f in v['files'].items():
                    if fid not in {e['file_id'] for e in entries}:
                        for field in ('path','root'):
                            if f.get(field):f[field]=rebased(f[field])
                v['roots'] = sorted(roots) + extras
                if first:
                    c.execute('INSERT INTO libraries VALUES(?,?,?)', (key,1,json.dumps(v,ensure_ascii=False)))
                else:
                    c.execute('UPDATE libraries SET payload=? WHERE id=?', (json.dumps(v,ensure_ascii=False),key))
    finally:
        c.close()
    if first:
        staged.replace(target)


def restore(root=ROOT):
    root = Path(root).resolve()
    bundle, digest = checked_bundle(root)
    data = root / 'data'
    data.mkdir(exist_ok=True)
    marker_path = data / 'submission-installation.json'
    previous = json.loads(marker_path.read_text(encoding='utf-8')) if marker_path.exists() else None
    if previous and previous['bundle_sha256'] != digest:
        raise ValueError('Different bundle already installed; use a new directory')
    if previous and previous['root'] == str(root):
        if not (data/'folders.db').is_file() or bundle.get('regulation_snapshot') and not (data/'regulation-monitor.db').is_file():
            raise ValueError('Installed database is missing; refusing to report a successful restore')
        for entry in bundle['sources']:
            if entry.get('reference_kind')=='system_manual':manual_copy(root,entry,previous)
        return dict(status='already_restored', sources=len(bundle['sources']), bundle_sha256=digest)
    lock = data / 'submission-restore.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        if not previous and any((data/name).exists() for name in ('regulation-monitor.db','folders.db')):
            raise ValueError('Existing databases found; restore into an empty installation')
        install_knowledge(root,bundle,previous)
        if not previous and bundle.get('regulation_snapshot'):
            snapshot = json.loads(safe_path(root,bundle['regulation_snapshot']['asset']).read_text(encoding='utf-8'))
            with sqlite3.connect(data/'regulation-monitor.db') as c:
                c.executescript('''
                CREATE TABLE settings(id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL DEFAULT 1,interval_hours INTEGER NOT NULL DEFAULT 24,revision INTEGER NOT NULL DEFAULT 1,next_check_at TEXT NOT NULL);
                CREATE TABLE runs(id TEXT PRIMARY KEY,status TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,lease_until TEXT NOT NULL,result_json TEXT NOT NULL);
                CREATE TABLE active(id INTEGER PRIMARY KEY CHECK(id=1),base_sha TEXT NOT NULL,pack_json TEXT NOT NULL);
                CREATE TABLE changes(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL UNIQUE,signature TEXT NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL,detected_at TEXT NOT NULL,last_seen TEXT NOT NULL,detail_json TEXT NOT NULL);
                ''')
                c.execute('INSERT INTO settings VALUES(1,0,24,1,?)',(datetime.now(timezone.utc).isoformat(),))
                if snapshot.get('active'):
                    row=snapshot['active']
                    c.execute('INSERT INTO active VALUES(1,?,?)',(row['base_sha'],row['pack_json']))
                for row in snapshot.get('runs',[]):
                    c.execute('INSERT INTO runs VALUES(?,?,?,?,?,?)',tuple(row[k] for k in ('id','status','started_at','finished_at','lease_until','result_json')))
                for row in snapshot.get('changes',[]):
                    c.execute('INSERT INTO changes VALUES(?,?,?,?,?,?,?,?)',tuple(row[k] for k in ('id','fingerprint','signature','state','revision','detected_at','last_seen','detail_json')))
            for item in bundle.get('regulation_objects',[]):
                raw=safe_path(root,item['asset']).read_bytes()
                target=data/'regulation-monitor/objects'/item['sha256'];target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(raw)
        if not (root/'config.json').exists():
            cfg=json.loads((root/'config.example.json').read_text(encoding='utf-8'))
            cfg['server']=dict(host='127.0.0.1',port=8781,open_browser=False)
            write_json(root/'config.json',cfg)
        write_json(marker_path,dict(format=1,root=str(root),bundle_sha256=digest,sources=len(bundle['sources'])))
        return dict(status='rebased' if previous else 'restored',sources=len(bundle['sources']),bundle_sha256=digest)
    finally:
        lock.unlink()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(restore(),ensure_ascii=False))
