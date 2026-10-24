"""설정·사용 DB·가상환경을 제외하고 제출 후보를 새 폴더에 복사한다."""
import argparse
import hashlib
import json
import shutil
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dest',required=True);parser.add_argument('--wheels',required=True)
    args=parser.parse_args();dest=Path(args.dest).resolve();wheels=Path(args.wheels).resolve()
    if dest.exists(): raise SystemExit('대상 폴더가 이미 있습니다. 기존 파일을 덮어쓰지 않습니다.')
    if dest==ROOT or ROOT in dest.parents: raise SystemExit('검증 폴더는 원본 프로젝트 밖에 만드세요.')
    if not list(wheels.glob('*.whl')): raise SystemExit('동봉할 wheel 파일이 없습니다.')
    dest.mkdir(parents=True)
    ignored=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo')
    for directory in ['app','static','sample_data','reference_data','tools','tests']:
        shutil.copytree(ROOT/directory,dest/directory,ignore=ignored)
    docs=dest/'docs';docs.mkdir()
    for file in (ROOT/'docs').glob('*.md'): shutil.copyfile(file,docs/file.name)
    shutil.copyfile(ROOT/'docs'/'openapi.json',docs/'openapi.json')
    if (ROOT/'docs'/'local-ai-evidence').exists(): shutil.copytree(ROOT/'docs'/'local-ai-evidence',docs/'local-ai-evidence')
    for file in ['README.md','requirements.txt','requirements-travel.lock.txt','config.example.json','run-seomu.bat','run-travel.bat','run.bat','.gitignore']:
        shutil.copyfile(ROOT/file,dest/file)
    shutil.copytree(wheels,dest/'wheels')
    assert not any((dest/p).exists() for p in ['config.json','data','.venv','output'])
    files=[p for p in dest.rglob('*') if p.is_file()]
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'excluded':['config.json','data/','.venv/','output/','__pycache__/'],
              'wheel_target':'Windows x64 CPython 3.12','files':{p.relative_to(dest).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}}
    (dest/'submission-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'candidate':str(dest),'files':len(files)+1,'wheels':len(list((dest/'wheels').glob('*.whl'))),'bytes':sum(p.stat().st_size for p in files)},ensure_ascii=False))


if __name__=='__main__': main()
