"""Match only locally collected, hash-checked official article excerpts."""
from pathlib import Path
from urllib.parse import urlsplit
import hashlib,json
BASE=Path(__file__).resolve().parents[1]/'reference_data/official-20261020'
def metadata(sha):
    manifest=BASE/'manifest.json'
    if not manifest.exists():return None
    for row in json.loads(manifest.read_text(encoding='utf-8')):
        if row.get('sha256')!=sha:continue
        if urlsplit(row.get('source_url','')).scheme!='https' or urlsplit(row['source_url']).hostname not in {'law.go.kr','www.law.go.kr','mois.go.kr','www.mois.go.kr'}:return None
        excerpt=BASE/'excerpts'/row['filename'];raw=BASE/row['raw_file']
        if excerpt.parent!=BASE/'excerpts' or raw.parent!=BASE:return None
        try:
            if hashlib.sha256(excerpt.read_bytes()).hexdigest()!=sha or hashlib.sha256(raw.read_bytes()).hexdigest()!=row['raw_sha256']:return None
        except OSError:return None
        return row
    return None
