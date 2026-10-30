"""Consistent stopped-volume backup/restore. Code deployment never calls this automatically."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.cloud_release import owned_state, write_json


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


@contextmanager
def stopped_volume(root):
    owned_state(root)
    with (root / 'cloud-runtime.lock').open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Stop the app/tunnel before backing up or restoring this volume.') from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def backup(root, output, staging_root=None):
    root, output = root.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError('Choose a new backup outside the live data volume.')
    output.parent.mkdir(parents=True, exist_ok=True)
    staging_root = (staging_root or output.parent).resolve()
    if staging_root.is_relative_to(root):
        raise ValueError('Backup staging must be outside the live volume on a private backup disk.')
    staging_root.mkdir(parents=True, exist_ok=True)
    with stopped_volume(root), tempfile.TemporaryDirectory(dir=staging_root) as tmp:
        staged = Path(tmp)
        files = {}
        for source in sorted(root.rglob('*')):
            if source.is_symlink():
                raise ValueError('Backup refuses symbolic links.')
            if not source.is_file() or source.name == 'cloud-runtime.lock' or source.name.endswith(('-wal', '-shm', '-journal')):
                continue
            name = source.relative_to(root).as_posix()
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix == '.db':
                with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as old, sqlite3.connect(target) as new:
                    old.backup(new)
                    if new.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('Database integrity check failed.')
            else:
                shutil.copyfile(source, target)
            files[name] = {'sha256': sha(target), 'bytes': target.stat().st_size}
        write_json(staged / 'backup-manifest.json', {'format': 1, 'data_format': 1, 'files': files})
        # Exclusive creation protects existing backups and restricts private data permissions.
        with output.open('xb') as stream:
            output.chmod(0o600)
            with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                for source in sorted(staged.rglob('*')):
                    if source.is_file():
                        archive.add(source, arcname=source.relative_to(staged).as_posix(), recursive=False)
    return {'status': 'backed_up', 'sha256': sha(output), 'bytes': output.stat().st_size,
            'files': len(files), 'data_format': 1, 'requires_private_storage': True}


def restore(archive, expected, destination, staging_root=None):
    destination = destination.resolve()
    if destination.is_relative_to(ROOT) or destination.exists() and any(destination.iterdir()):
        raise ValueError('Restore only into a new empty volume outside the release directory.')
    if sha(archive) != expected:
        raise ValueError('Backup SHA256 does not match the recorded backup receipt.')
    staging_root = (staging_root or archive.parent).resolve()
    if staging_root.is_relative_to(destination):
        raise ValueError('Restore staging must use a separate private disk directory.')
    staging_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging_root) as tmp, tarfile.open(archive, 'r:gz') as tar:
        staged = Path(tmp)
        members = tar.getmembers()
        if len(members) > 100000 or sum(item.size for item in members) > 16 * 1024**3:
            raise ValueError('Backup exceeds the restore safety limit.')
        names = set()
        for member in members:
            name = PurePosixPath(member.name)
            if (not member.isfile() or name.is_absolute() or '..' in name.parts or
                    '\\' in member.name or ':' in member.name or member.name in names):
                raise ValueError('Invalid or duplicate backup path.')
            names.add(member.name)
            target = staged.joinpath(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as old, target.open('xb') as new:
                shutil.copyfileobj(old, new)
        manifest = json.loads((staged / 'backup-manifest.json').read_text())
        if manifest.get('format') != 1 or names != set(manifest['files']) | {'backup-manifest.json'}:
            raise ValueError('Invalid backup file manifest.')
        for name, value in manifest['files'].items():
            target = staged / name
            if sha(target) != value['sha256'] or target.stat().st_size != value['bytes']:
                raise ValueError('Backup file integrity mismatch.')
        owned_state(staged)
        for db in (staged / 'data').rglob('*.db'):
            with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as connection:
                if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Restored database integrity check failed.')
        shutil.copytree(staged, destination, dirs_exist_ok=True)
    # Explicit restore rebases package-owned and user-added paths, without replacing source contents.
    sys.path.insert(0, str(ROOT / 'service'))
    spec = importlib.util.spec_from_file_location('backup_submission_restore', ROOT / 'service/tools/restore_submission.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.restore(destination)
    (destination / 'backup-manifest.json').unlink()
    return {'status': 'restored', 'data_format': 1, 'code_deployed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    save = commands.add_parser('backup')
    save.add_argument('--data-root', type=Path, required=True)
    save.add_argument('--output', type=Path, required=True)
    save.add_argument('--staging-root', type=Path)
    load = commands.add_parser('restore')
    load.add_argument('--archive', type=Path, required=True)
    load.add_argument('--sha256', required=True)
    load.add_argument('--data-root', type=Path, required=True)
    load.add_argument('--staging-root', type=Path)
    args = parser.parse_args()
    try:
        result = backup(args.data_root, args.output, args.staging_root) if args.command == 'backup' else restore(args.archive, args.sha256, args.data_root, args.staging_root)
    except (OSError, ValueError, sqlite3.Error, tarfile.TarError) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False))
