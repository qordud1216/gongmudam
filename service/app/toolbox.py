"""Tool output reference files. Receipt parsing and XLSX merging keep their own APIs."""
import hashlib
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import quote
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from . import adhoc, travel_api

Kind = Literal['travel', 'adhoc']
router = APIRouter(prefix='/api/toolbox', tags=['업무도구함 첨부'])
MAX_BYTES = 20 * 1024 * 1024
MAX_FILES = 50
MAX_TOTAL = 200 * 1024 * 1024
TYPES = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg',
         '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif',
         '.txt': 'text/plain', '.csv': 'text/csv', '.zip': 'application/zip',
         '.hwpx': 'application/hwp+zip', '.odt': 'application/vnd.oasis.opendocument.text',
         '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}


def owner(kind):
    if kind == 'travel':
        return travel_api
    if kind == 'adhoc':
        return adhoc
    raise HTTPException(422, '출장정산 또는 자료 취합 업무를 선택하세요.')


def initialize():
    for module, table in ((travel_api, 'travel_cases'), (adhoc, 'jobs')):
        with module.db() as c:
            c.executescript(f'''CREATE TABLE IF NOT EXISTS toolbox_attachments(
              id TEXT PRIMARY KEY, target_id TEXT NOT NULL REFERENCES {table}(id),
              filename TEXT NOT NULL, media_type TEXT NOT NULL, sha256 TEXT NOT NULL,
              original BLOB NOT NULL, source_tool TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(target_id,sha256));''')


def target(c, kind, key):
    if kind == 'travel':
        row = travel_api.get_case(c, key)
        trip = row['trip_json']
        return dict(kind=kind, id=key, version=row['version'],
                    title=f"{trip['destination']} · {trip['purpose']}",
                    subtitle=f"출장정산 · {trip['start_date']}~{trip['end_date']}",
                    url=f'travel.html?case={quote(key)}#settle', departments=[])
    row = adhoc.job(c, key)
    return dict(kind=kind, id=key, version=row['version'], title=row['settings']['title'],
                subtitle=f"자료 취합 · {row['settings']['course']}",
                url=f'adhoc.html#job-{quote(key)}', departments=row['settings']['departments'])


def items(c, kind, key):
    rows = c.execute('''SELECT id,filename,media_type,sha256,length(original) AS size,
                        source_tool,created_at FROM toolbox_attachments
                        WHERE target_id=? ORDER BY created_at,id''', (key,))
    return [dict(r) | {'original_url': f'/api/toolbox/{kind}/{quote(key)}/attachments/{r["id"]}/original'}
            for r in rows]


@router.get('/targets')
def targets():
    result = []
    for kind, table, order in (('travel', 'travel_cases', 'updated_at'), ('adhoc', 'jobs', 'created_at')):
        with owner(kind).db() as c:
            keys = c.execute(f'SELECT id FROM {table} ORDER BY {order} DESC,id LIMIT 100').fetchall()
            result.extend(target(c, kind, r['id']) for r in keys)
    return {'targets': result, 'max_bytes': MAX_BYTES, 'extensions': list(TYPES)}


@router.get('/{kind}/{key}/attachments')
def listing(kind: Kind, key: str):
    with owner(kind).db() as c:
        return {'target': target(c, kind, key), 'items': items(c, kind, key)}


def checked_file(filename, raw):
    name = ''.join(ch for ch in (filename or '').replace('\\', '/').split('/')[-1] if ch.isprintable())[:180]
    ext = PurePosixPath(name).suffix.lower()
    if ext not in TYPES:
        raise HTTPException(422, 'PDF·사진·TXT·CSV·ZIP·HWPX·ODT·XLSX 파일을 첨부할 수 있습니다.')
    if not raw or len(raw) > MAX_BYTES:
        raise HTTPException(422, '참고 첨부는 1바이트~20MB 파일을 지원합니다.')
    valid = (raw.startswith(b'%PDF-') if ext == '.pdf' else
             raw.startswith(b'\x89PNG\r\n\x1a\n') if ext == '.png' else
             raw.startswith(b'\xff\xd8\xff') if ext in ('.jpg', '.jpeg') else
             raw[:6] in (b'GIF87a', b'GIF89a') if ext == '.gif' else
             raw.startswith(b'RIFF') and raw[8:12] == b'WEBP' if ext == '.webp' else
             raw.startswith((b'PK\x03\x04', b'PK\x05\x06')) if ext in ('.zip', '.hwpx', '.odt', '.xlsx') else True)
    if not valid:
        raise HTTPException(422, '확장자와 파일 형식이 일치하지 않습니다.')
    return name, TYPES[ext]


@router.post('/{kind}/{key}/attachments', status_code=201)
async def attach(kind: Kind, key: str, version: int = Form(..., ge=1),
                 source_tool: str = Form('', max_length=40, pattern=r'^[a-z0-9-]*$'),
                 file: UploadFile = File(...)):
    try:
        raw = await file.read(MAX_BYTES + 1)
    finally:
        await file.close()
    name, media = checked_file(file.filename, raw)
    digest = hashlib.sha256(raw).hexdigest()
    module = owner(kind)
    with module.db() as c:
        c.execute('BEGIN IMMEDIATE')
        current = target(c, kind, key)
        if current['version'] != version:
            raise HTTPException(409, '업무 내용이 바뀌었습니다. 업무 목록을 새로고침하고 첨부할 업무를 다시 확인하세요. 만든 파일은 유지됩니다.')
        previous = c.execute('SELECT id FROM toolbox_attachments WHERE target_id=? AND sha256=?', (key, digest)).fetchone()
        if previous:
            return {'target': current, 'items': items(c, kind, key), 'attachment_id': previous['id'], 'duplicate': True}
        size = c.execute('SELECT COUNT(*) AS n,COALESCE(SUM(length(original)),0) AS bytes FROM toolbox_attachments WHERE target_id=?', (key,)).fetchone()
        if size['n'] >= MAX_FILES or size['bytes'] + len(raw) > MAX_TOTAL:
            raise HTTPException(422, '업무별 참고 첨부는 최대 50개·전체 200MB까지 지원합니다.')
        ident = uuid.uuid4().hex
        now = travel_api.now()
        c.execute('INSERT INTO toolbox_attachments VALUES (?,?,?,?,?,?,?,?)',
                  (ident, key, name, media, digest, raw, source_tool, now))
        payload = dict(attachment_id=ident, filename=name, sha256=digest, source_tool=source_tool,
                       role='reference', version=current['version'])
        if kind == 'travel':
            travel_api.event(c, key, 'TOOLBOX_FILE_ATTACHED', payload)
            c.execute('UPDATE travel_cases SET updated_at=? WHERE id=?', (now, key))
        else:
            adhoc.log(c, key, '도구함 참고 파일 첨부', payload)
        # Reference files do not change calculation/roster versions or approve work.
        return {'target': current, 'items': items(c, kind, key), 'attachment_id': ident, 'duplicate': False}


@router.get('/{kind}/{key}/attachments/{attachment_id}/original')
def original(kind: Kind, key: str, attachment_id: str):
    with owner(kind).db() as c:
        target(c, kind, key)
        row = c.execute('SELECT * FROM toolbox_attachments WHERE target_id=? AND id=?', (key, attachment_id)).fetchone()
        if not row:
            raise HTTPException(404, '이 업무의 첨부파일을 찾을 수 없습니다.')
        if hashlib.sha256(row['original']).hexdigest() != row['sha256']:
            raise HTTPException(409, '첨부 원본의 무결성을 확인하세요.')
        return Response(row['original'], media_type=row['media_type'],
                        headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(row['filename']),
                                 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'})
