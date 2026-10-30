"""Build an allowlisted development release, separately from the original sealed package."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ('service/app/', 'service/static/', 'service/sample_data/', 'service/reference_data/',
            'service/submission-data/', 'integration/', 'deploy/', 'tests/')
EXACT = {'service/config.example.json', 'service/submission-manifest.json',
         'service/requirements-cloud.lock.txt', 'service/tools/restore_submission.py',
         'tools/cloud_release.py', 'tools/build_cloud_release.py', 'tools/cloud_backup.py',
         'tools/cloud_smoke.py', 'tools/render_cloudflare_config.py',
         'tools/verify_cloud_preview.py', 'tools/promote_cloud_release.py',
         'cloudflare/cloud-worker.js', 'README.md', 'docs/CLOUD-RELEASE.md', 'package.json', 'package-lock.json',
         'desktop/agency_directory.py',
         'desktop/data/agencies-v1.sqlite', 'desktop/data/agencies-v1.json'}


def allowed(name):
    if name == '.dockerignore':
        return True
    p = PurePosixPath(name)
    if any(part.startswith('.') or part == '__pycache__' for part in p.parts):
        return False
    if p.name == 'config.json' or p.suffix in {'.pyc', '.db', '.pem', '.key', '.p12', '.env'}:
        return False
    if name in EXACT or name.startswith(PREFIXES):
        return True
    return name.startswith('desktop/') and (
        len(p.parts) == 2 and p.suffix in {'.html', '.js', '.css'} or
        len(p.parts) > 2 and p.parts[1] == 'assets' and p.suffix in {'.svg', '.png', '.woff2', '.txt'})


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output, allow_dirty=False):
    output = output.resolve()
    if output == ROOT or output.is_relative_to(ROOT / 'service') or output.exists():
        raise ValueError('Choose a new release output directory outside service/.')
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip())
    if dirty and not allow_dirty:
        raise ValueError('Commit the tested changes before building a promotable release; use --allow-dirty only for development tests.')
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    arguments = ['git', 'ls-files', '-z']
    if allow_dirty:
        arguments += ['--cached', '--others', '--exclude-standard']
    names = sorted(set(subprocess.check_output(arguments, cwd=ROOT).decode().split('\0')))
    output.mkdir(parents=True)
    files = {}
    for name in names:
        if not name or not allowed(name):
            continue
        original = ROOT / name
        if original.is_symlink() or not original.is_file():
            raise ValueError('Missing/link release input: ' + name)
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        files[name] = sha(target)
    metadata = {'format': 1, 'kind': 'derived-development-release', 'source_commit': source,
                'source_dirty': dirty, 'files': files,
                'original_seal_sha256': sha(ROOT / 'service/submission-manifest.json'),
                'original_seal_is_development_approval': False,
                'data_format': 1, 'llm_enabled': False}
    metadata['release_id'] = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    (output / 'development-release.json').write_text(json.dumps(metadata, indent=2) + '\n')
    archive = output.with_suffix('.tar.gz')
    if archive.exists():
        raise ValueError('Existing release archive will not be overwritten.')
    with tarfile.open(archive, 'w:gz') as tar:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(output).as_posix(), recursive=False)
    return {'release_id': metadata['release_id'], 'source_commit': source, 'source_dirty': dirty,
            'files': len(files), 'archive': str(archive), 'archive_sha256': sha(archive)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-dirty', action='store_true')
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.allow_dirty), ensure_ascii=False))
