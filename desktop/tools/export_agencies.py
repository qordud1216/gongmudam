"""Copy only public agency directory tables from LEX-FLOW, read-only at source."""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE TB_AGENCY (
 code TEXT PRIMARY KEY, full_name TEXT NOT NULL, short_name TEXT NOT NULL,
 parent_code TEXT, root_code TEXT, representative_code TEXT, depth INTEGER NOT NULL,
 type_large TEXT, type_large_name TEXT, type_medium TEXT, type_medium_name TEXT,
 type_small TEXT, type_small_name TEXT, abolished INTEGER NOT NULL,
 created_at TEXT, abolished_at TEXT, changed_at TEXT, previous_code TEXT
);
CREATE INDEX IDX_AGENCY_PARENT ON TB_AGENCY(parent_code,abolished,code);
CREATE INDEX IDX_AGENCY_TYPE ON TB_AGENCY(type_large,abolished,code);
CREATE INDEX IDX_AGENCY_NAME ON TB_AGENCY(short_name,code);
CREATE VIRTUAL TABLE TB_AGENCY_FTS USING fts5(
 full_name,short_name,code,content='TB_AGENCY',content_rowid='rowid',tokenize='trigram'
);
CREATE TABLE DIRECTORY_METADATA (id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
"""


def export(source: Path, destination: Path):
    if destination.exists():
        raise FileExistsError('Destination exists; choose a new snapshot filename.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A transaction gives a consistent view of the live WAL database, without writes.
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as origin:
        origin.execute('PRAGMA query_only=ON')
        origin.execute('BEGIN')
        metadata = json.loads(origin.execute(
            'SELECT payload_json FROM TB_AGENCY_SNAPSHOT ORDER BY fetched_at DESC,rowid DESC LIMIT 1'
        ).fetchone()[0])
        rows = origin.execute('''WITH RECURSIVE included(code) AS (
          SELECT code FROM TB_AGENCY WHERE abolished=0
          UNION
          SELECT a.parent_code FROM TB_AGENCY a JOIN included i ON a.code=i.code
          WHERE a.parent_code IS NOT NULL
        ) SELECT a.* FROM TB_AGENCY a JOIN included i ON a.code=i.code ORDER BY a.code''')
        with sqlite3.connect(destination) as target:
            target.executescript(SCHEMA)
            target.executemany('INSERT INTO TB_AGENCY VALUES (' + ','.join('?' * 18) + ')', rows)
            target.execute("INSERT INTO TB_AGENCY_FTS(TB_AGENCY_FTS) VALUES('rebuild')")
            count, active = target.execute('SELECT count(*),sum(abolished=0) FROM TB_AGENCY').fetchone()
            payload = {key: metadata.get(key) for key in (
                'snapshotId', 'sourceUrl', 'sourceUpdatedAt', 'fetchedAt', 'sha256', 'counts')}
            payload.update(exportedAt=datetime.now(timezone.utc).isoformat(),
                           exportCounts={'total': count, 'active': active},
                           derivation='LEX-FLOW active agency records plus their ancestors; no other source tables')
            target.execute('INSERT INTO DIRECTORY_METADATA VALUES(1,?)',
                           (json.dumps(payload, ensure_ascii=False),))
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    manifest = {**payload, 'databaseSha256': digest, 'databaseBytes': destination.stat().st_size}
    destination.with_suffix('.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.source, args.destination), ensure_ascii=True))
