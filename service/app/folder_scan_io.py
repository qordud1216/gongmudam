"""Bounded, sequential original-file reads. No upload copies or model calls."""
from __future__ import annotations
import copy
import codecs
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import uuid
from . import folders

PROFILE = 'direct-v63'
MAX_FILES = 10_000
MAX_ENTRIES = 50_000
MAX_DEPTH = 32
HASH_BYTES = 256 * 1024 * 1024
PREVIEW_BYTES = 64 * 1024 * 1024
PARSE_SECONDS = 45
CHUNK = 1024 * 1024


class Cancelled(Exception):
    pass


def check_path(path, root):
    if path.is_symlink() or path.is_junction() or not path.resolve(strict=True).is_relative_to(root):
        raise ValueError('연결점 또는 폴더 경계 변경')


def text_preview(stream):
    sample = stream.read(65536); stream.seek(0)
    try:
        codecs.getincrementaldecoder('utf-8-sig')().decode(sample, final=False); encoding = 'utf-8-sig'
    except UnicodeDecodeError:
        encoding = 'cp949'
    wrapper = io.TextIOWrapper(stream, encoding=encoding, errors='replace')
    units = []; limited = False
    try:
        for n in range(1, 257):
            line = wrapper.readline(2001)
            if not line: break
            if len(line) > 2000: limited = True
            if line.strip(): units.append({'text': line.strip()[:2000], 'loc': f'{n}행·분할 단위'})
        limited = limited or bool(wrapper.read(1))
    finally:
        wrapper.detach()
    return units, '분류용 본문 일부 확인' if limited else '본문 확인' if units else '추출 본문 없음', limited


def document_preview(path, root, expected, tick):
    """Own one parser child at a time so cancellation and parser deadlines work."""
    payload = json.dumps({'path': str(path), 'root': str(root), 'size': expected.st_size, 'mtime_ns': expected.st_mtime_ns}).encode()
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    process = subprocess.Popen([sys.executable, '-m', 'app.folder_scan_io', '--extract'],
        cwd=str(Path(__file__).resolve().parents[1]), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    deadline = time.monotonic() + PARSE_SECONDS
    first = True
    try:
        while True:
            tick()
            if time.monotonic() > deadline: raise ValueError('문서 읽기 시간 초과 · 다시 확인 필요')
            try:
                output, error = process.communicate(input=payload if first else None, timeout=.25)
                if process.returncode: raise ValueError('본문 읽기 실패 · 암호·손상·해석 범위 확인')
                result = json.loads(output.decode('utf-8'))
                if 'error' in result: raise ValueError(result['error'])
                return result['units'], result['status'], result['limited']
            except subprocess.TimeoutExpired:
                first = False
    finally:
        if process.poll() is None:
            process.kill()  # Only the parser process created above, never the app server.
        process.communicate()


def collect(roots, previous=None, progress=None):
    previous = previous or {}
    old_by_path = {folders.path_key(Path(f['path'])): f for f in previous.values() if f.get('path')}
    state = dict(phase='discovering', discovered=0, processed=0, reused=0, failed_files=0,
                 limited_files=0, current_file='', current_bytes=0, total_bytes=0, bytes_read=0, total=None)
    def tick(**changes):
        state.update(changes)
        if progress: progress(dict(state))
    found = []; warnings = []; seen = set(); entries_seen = 0; exhausted = False
    tick()
    for root in roots:
        stack = [(root, 0)]
        while stack and not exhausted:
            directory, depth = stack.pop()
            try:
                check_path(directory, root)
                with os.scandir(directory) as entries:
                    candidates = []
                    for entry in entries:
                        entries_seen += 1
                        if entries_seen > MAX_ENTRIES:
                            warnings.append(f'탐색 {MAX_ENTRIES:,}항목 범위에 도달했습니다. 남은 폴더는 나눠 연결하세요.'); exhausted = True; break
                        candidates.append(Path(entry.path))
                        if entries_seen % 100 == 0: tick(current_file=directory.name)
                for path in sorted(candidates, key=lambda p: p.name.casefold()):
                    tick(current_file=path.name)
                    try:
                        if path.is_symlink() or path.is_junction() or path.name.startswith('.') or path.name.casefold() in folders.SKIP: continue
                        before = path.stat()
                        attributes = getattr(before, 'st_file_attributes', 0)
                        if attributes & (getattr(stat, 'FILE_ATTRIBUTE_HIDDEN', 2) | getattr(stat, 'FILE_ATTRIBUTE_SYSTEM', 4) | getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024)): continue
                        if path.is_dir():
                            if depth < MAX_DEPTH: stack.append((path, depth + 1))
                            else: warnings.append(f'하위 {MAX_DEPTH}단계 범위: {path.name} · 전체 탐색 아님')
                        elif path.is_file() and folders.path_key(path) not in seen:
                            if len(found) >= MAX_FILES:
                                warnings.append(f'파일 {MAX_FILES:,}개 범위에 도달했습니다. 남은 폴더는 나눠 연결하세요.'); exhausted = True; break
                            check_path(path, root); seen.add(folders.path_key(path)); found.append((path, root, before)); tick(discovered=len(found))
                    except (OSError, ValueError):
                        warnings.append(f'파일 또는 하위 폴더 미확인: {path.name}')
            except (OSError, ValueError) as exc:
                warnings.append(f'폴더 또는 파일 미확인: {directory.name}')
    tick(phase='reading', total=len(found), total_bytes=sum(s.st_size for _, _, s in found), current_file='')
    files = {}
    # Bound the retained preview across a large library, not cumulative source
    # bytes. Every file is still catalogued and hashed within the per-file cap.
    preview_budget = min(512_000, max(1, 16_000_000 // max(1, len(found))))
    for path, root, before in found:
        fid = uuid.uuid5(uuid.NAMESPACE_URL, folders.path_key(path)).hex
        item = dict(id=fid, path=str(path), name=path.name, root=str(root), size=before.st_size,
                    mtime_ns=before.st_mtime_ns, sha256='', units=[], present=True, status='', limited=False, scan_profile=PROFILE)
        tick(current_file=path.name, current_bytes=0)
        old = old_by_path.get(folders.path_key(path))
        failed = False
        try:
            check_path(path, root)
            actual = path.stat()
            if (actual.st_size, actual.st_mtime_ns) != (before.st_size, before.st_mtime_ns): raise ValueError('파일 변경 중 · 재분석 필요')
            if (old and old.get('scan_profile') == PROFILE and old.get('sha256')
                    and (old.get('size'), old.get('mtime_ns')) == (before.st_size, before.st_mtime_ns)):
                item.update(sha256=old['sha256'], units=copy.deepcopy(old.get('units', [])), status=old['status'], limited=old.get('limited', False))
                state['reused'] += 1
            elif before.st_size > HASH_BYTES:
                item.update(status='256MB 초과 · 파일 정보만 확인, 본문 분석은 파일 분할 후 진행', limited=True)
            else:
                with path.open('rb') as stream:
                    digest = hashlib.sha256(); read = 0
                    while chunk := stream.read(CHUNK):
                        digest.update(chunk); read += len(chunk)
                        if read > HASH_BYTES: raise ValueError('분석 중 파일 크기 변경')
                        state['bytes_read'] += len(chunk); tick(current_bytes=read)
                    item['sha256'] = digest.hexdigest()
                    stream.seek(0)
                    if path.suffix.lower() in {'.txt', '.md', '.csv'}:
                        item['units'], item['status'], item['limited'] = text_preview(stream)
                    elif path.suffix.lower() not in {'.xlsx', '.docx', '.hwpx', '.pdf'}:
                        item['status'] = '본문 미지원 · 파일명만 확인'
                    elif before.st_size > PREVIEW_BYTES:
                        item.update(status='64MB 초과 문서 · 파일 정보·해시 확인, 본문은 분할 후 분석', limited=True)
                    else:
                        item['units'], item['status'], item['limited'] = document_preview(path, root, before, lambda: tick())
                check_path(path, root)
                after = path.stat()
                if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns): raise ValueError('분석 중 파일 변경 · 재분석 필요')
        except (OSError, ValueError) as exc:
            item.update(sha256='', units=[], status=str(exc) if isinstance(exc, ValueError) else '파일 읽기 실패 · 권한·잠금·경로 확인', limited=True)
            state['failed_files'] += 1; failed = True
        retained = []; remaining = preview_budget
        for unit in item['units']:
            if remaining <= 0: break
            text = unit['text'][:remaining]; remaining -= len(text)
            retained.append({'text': text, 'loc': unit['loc']})
        if sum(len(u['text']) for u in retained) < sum(len(u['text']) for u in item['units']):
            item.update(limited=True, status='분류용 본문 일부 확인 · 자료함 미리보기 범위')
        item['units'] = retained
        if item['limited'] and not failed: state['limited_files'] += 1
        item['clues'] = folders.clues(path.name, item['units']); files[fid] = item
        tick(processed=state['processed'] + 1)
    tick(phase='saving', current_file='', current_bytes=0)
    return files, warnings


def extract_child():
    try:
        value = json.load(sys.stdin)
        path = Path(value['path']); root = Path(value['root'])
        check_path(path, root); before = path.stat()
        if before.st_size > PREVIEW_BYTES or (before.st_size, before.st_mtime_ns) != (value['size'], value['mtime_ns']): raise ValueError('문서 변경 또는 본문 처리 범위 초과')
        with path.open('rb') as stream: raw = stream.read(PREVIEW_BYTES + 1)
        if len(raw) > PREVIEW_BYTES: raise ValueError('본문 처리 범위 초과')
        units, status, limited = folders.extract(path, raw)
        check_path(path, root); after = path.stat()
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns): raise ValueError('문서 변경 · 재분석 필요')
        print(json.dumps(dict(units=units, status=status, limited=limited), ensure_ascii=True))
    except Exception:
        print(json.dumps({'error': '본문 읽기 실패 · 암호·손상·문서 해석 범위 확인'}))


if __name__ == '__main__': extract_child()
