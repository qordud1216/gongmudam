"""Explicit cloud-volume initialization. Never import a user's existing database."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / 'service'
MARKER = 'cloud-installation.json'
STORES = {'folders.db': 'libraries', 'seomu.db': 'documents', 'travel.db': 'travel_cases',
          'adhoc.db': 'jobs', 'calendar.db': 'calendar_events', 'regulation-monitor.db': 'settings'}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def verify_release(root):
    """One integrity contract for startup and promotion; this is not a signature/legal approval."""
    root = root.resolve()
    value = json.loads((root / 'development-release.json').read_text(encoding='utf-8'))
    if (value.get('format') != 1 or value.get('kind') != 'derived-development-release' or
            not re.fullmatch('[0-9a-f]{40}', value.get('source_commit', '')) or
            not isinstance(value.get('files'), dict) or not value['files']):
        raise ValueError('Invalid development release manifest.')
    expected = dict(value)
    identity = expected.pop('release_id', '')
    canonical = hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if not re.fullmatch('[0-9a-f]{64}', identity) or identity != canonical:
        raise ValueError('Development release identity mismatch.')
    for name, checksum in value['files'].items():
        target = (root / name).resolve()
        if not target.is_relative_to(root) or not target.is_file() or digest(target) != checksum:
            raise ValueError('Development release file mismatch: ' + name)
    return value


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def owned_state(path):
    if not path.is_absolute() or path.resolve().is_relative_to(ROOT):
        raise ValueError('Choose an absolute data volume outside the source/release directory.')
    path = path.resolve()
    marker = path / MARKER
    if not marker.is_file():
        raise ValueError('Initialize a new cloud data volume explicitly before starting.')
    value = json.loads(marker.read_text(encoding='utf-8'))
    if value.get('format') != 1 or value.get('mode') != 'operator-private-no-llm':
        raise ValueError('Unrecognized cloud data volume; no files were replaced.')
    for name in ('config.json', 'data/submission-installation.json', *('data/' + name for name in STORES)):
        if not (path / name).is_file():
            raise ValueError('Cloud state is incomplete; inspect or restore a consistent backup.')
    for name, table in STORES.items():
        try:
            with sqlite3.connect((path / 'data' / name).as_uri() + '?mode=ro', uri=True) as connection:
                found = connection.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (table,)).fetchone()
                if not found:
                    raise ValueError('Cloud state schema is incomplete; restore or migrate it explicitly.')
        except sqlite3.Error as error:
            raise ValueError('Cloud state database cannot be read; inspect the backup.') from error
    return value


def initialize(path):
    if not path.is_absolute() or path.resolve().is_relative_to(ROOT):
        raise ValueError('Choose an absolute data volume outside the source/release directory.')
    path = path.resolve()
    if (path / MARKER).exists():
        owned_state(path)
        return {'status': 'preserved', 'data_initialized': False}
    if path.exists() and any(path.iterdir()):
        raise ValueError('Existing unowned data found; initialize only an empty volume.')
    path.mkdir(parents=True, exist_ok=True)
    # These inputs already belong to the repository's archived submission bundle.
    # No scan/export of local registrations or personal databases is performed.
    shutil.copytree(SERVICE / 'submission-data', path / 'submission-data')
    rule = Path('app/rulepacks/domestic_reviewed_2026_10.json')
    (path / rule).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SERVICE / rule, path / rule)
    cfg = json.loads((SERVICE / 'config.example.json').read_text(encoding='utf-8'))
    cfg['llm'] = {'active': 'offline', 'profiles': {'offline': {'provider': 'offline'}}}
    cfg['server'] = {'host': '127.0.0.1', 'port': 8892, 'open_browser': False}
    write_json(path / 'config.example.json', cfg)
    write_json(path / 'config.json', cfg)
    os.environ.update(GONGMUDAM_DATA_ROOT=str(path), GONGMUDAM_NO_LLM='1', GONGMUDAM_CLOUD='1')
    sys.path.insert(0, str(SERVICE))
    spec = importlib.util.spec_from_file_location('cloud_submission_restore', SERVICE / 'tools/restore_submission.py')
    restore = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(restore)
    result = restore.restore(path)
    # Finish every store before recording ownership. Later startup may not
    # replace missing stores with empty databases and synthetic work.
    from app import main, store
    async def initialize_stores():
        async with main.app.router.lifespan_context(main.app):
            pass
    asyncio.run(initialize_stores())
    if store._conn is not None:
        store._conn.close()
        store._conn = None
    write_json(path / MARKER, {'format': 1, 'mode': 'operator-private-no-llm',
                              'initial_bundle_sha256': result['bundle_sha256'],
                              'original_seal_sha256': digest(SERVICE / 'submission-manifest.json')})
    return {'status': 'initialized', 'data_initialized': True,
            'archived_sources': result['sources'], 'automatic_source_updates': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('initialize')
    init.add_argument('--data-root', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = initialize(args.data_root)
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
