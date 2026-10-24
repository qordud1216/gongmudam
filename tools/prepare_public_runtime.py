"""Create a fresh shared demo from the verified package; preserve an existing demo."""
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'service'
DEST = ROOT / '.local-runtime/service'


def prepare():
    manifest_raw = (SOURCE / 'submission-manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    digest = hashlib.sha256(manifest_raw).hexdigest()
    marker = DEST / 'gongmudam-runtime.json'
    if DEST.exists():
        if marker.is_file() and json.loads(marker.read_text(encoding='utf-8')).get('source_manifest_sha256') == digest:
            return {'status': 'preserved', 'public_runtime': True}
        raise RuntimeError('Existing runtime differs or preparation was interrupted; inspect it before updating. No data was overwritten.')
    for name, expected in manifest['files'].items():
        source = (SOURCE / name).resolve()
        if not source.is_relative_to(SOURCE) or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Verified source mismatch: ' + name)
    DEST.mkdir(parents=True)
    for name in manifest['files']:
        if name.startswith('wheels/'):
            continue
        target = DEST / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / name, target)
    shutil.copyfile(SOURCE / 'submission-manifest.json', DEST / 'submission-manifest.json')
    subprocess.run([sys.executable, str(DEST / 'tools/restore_submission.py')], cwd=DEST, check=True)
    config = json.loads((DEST / 'config.example.json').read_text(encoding='utf-8'))
    config['server'] = {'host': '127.0.0.1', 'port': 8892, 'open_browser': False}
    models = {'local_gemma': 'gemma3:4b', 'local_llama': 'llama3.2:3b'}
    config['llm'] = {'active': 'local_gemma', 'profiles': {
        key: {'provider': 'openai_compatible', 'base_url': 'http://127.0.0.1:11434/v1',
              'model': model, 'api_key': '', 'temperature': 0.1, 'max_tokens': 900, 'timeout': 180}
        for key, model in models.items()}}
    (DEST / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    incoming = DEST / 'synthetic-folders/추가회신'
    incoming.mkdir(parents=True)
    (incoming / '교육_참석_안내.txt').write_text('합성 시연자료\n공공 AI 실무교육 참석 희망자를 취합합니다. 대상 부서는 총무과와 회계과입니다. 실제 개인정보를 입력하지 마세요.\n', encoding='utf-8')
    definition = {'mode': 'public-synthetic-demo', 'private_data_isolated': True,
                  'folder_library_id': 'gongmudam-demo', 'created_from': 'verified v69 public sources; no private databases'}
    (DEST / 'public-demo.json').write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding='utf-8')
    marker.write_text(json.dumps({'source_manifest_sha256': digest}, indent=2), encoding='utf-8')
    return {'status': 'created', 'public_sources': 31, 'private_data_copied': False}


if __name__ == '__main__':
    print(json.dumps(prepare(), ensure_ascii=False))
