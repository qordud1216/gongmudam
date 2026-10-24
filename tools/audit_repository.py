"""Verify source integrity and detect excluded local files before publishing."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    errors = []
    original = json.loads((ROOT / 'service/submission-manifest.json').read_text(encoding='utf-8'))
    for name, digest in original['files'].items():
        path = ROOT / 'service' / name
        if not path.is_file() or sha(path) != digest:
            errors.append({'file': 'service/' + name, 'reason': 'sealed-source-mismatch'})
    provenance = json.loads((ROOT / 'docs/source-provenance.json').read_text(encoding='utf-8'))
    for name, digest in provenance['desktop']['files'].items():
        path = ROOT / 'desktop' / name
        if not path.is_file() or sha(path) != digest:
            errors.append({'file': 'desktop/' + name, 'reason': 'desktop-copy-mismatch'})
    ignored_parts = {'.git', '.venv', '__pycache__', '.pytest_cache', '.local-verification', 'runtime-logs'}
    patterns = {
        'github-token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b'),
        'cloudflare-global-key': re.compile(r'(?i)(?:cloudflare_api_token|cf_api_token)\s*[=:]\s*[\"\'][A-Za-z0-9_-]{30,}'),
        'private-key-material': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
        'openai-token': re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}\b'),
    }
    text_suffixes = {'.py', '.js', '.json', '.html', '.css', '.md', '.txt', '.bat', '.cmd', '.yml', '.yaml'}
    files = []
    listing = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT,
                             check=True, capture_output=True).stdout.decode('utf-8').split('\0')
    for name in sorted(set(listing)):
        if not name:
            continue
        path = ROOT / name
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in ignored_parts for part in rel.parts) or rel.parts[:2] in (('service', 'data'), ('service', 'output')):
            continue
        if path.name == 'config.json' or path.name.startswith('.env') or path.suffix in ('.pem', '.key', '.pfx', '.p12'):
            errors.append({'file': rel.as_posix(), 'reason': 'private-file'})
        if path.stat().st_size >= 100 * 1024 * 1024:
            errors.append({'file': rel.as_posix(), 'reason': 'oversized-git-blob'})
        if path.suffix.lower() in text_suffixes:
            content = path.read_text(encoding='utf-8', errors='replace')
            for kind, pattern in patterns.items():
                for match in pattern.finditer(content):
                    errors.append({'file': rel.as_posix(), 'line': content.count('\n', 0, match.start()) + 1, 'reason': kind})
        files.append(path)
    report = {'service_files_verified': len(original['files']), 'desktop_files_verified': len(provenance['desktop']['files']),
              'candidate_files': len(files), 'candidate_bytes': sum(p.stat().st_size for p in files), 'errors': errors}
    print(json.dumps(report, ensure_ascii=True, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
