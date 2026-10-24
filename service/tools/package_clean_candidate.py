"""검증한 런타임 파일과 문서·증거만 새 제출 ZIP으로 구성한다."""
import argparse
import hashlib
import json
import zipfile
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',required=True);p.add_argument('--evidence',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    candidate=Path(args.candidate);evidence=Path(args.evidence);output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    tested=json.loads((candidate/'submission-manifest.json').read_text(encoding='utf-8'))
    report=json.loads((evidence/'clean-install-report.json').read_text(encoding='utf-8'))
    tests=json.loads((evidence/'fresh-unit-test-result.json').read_text(encoding='utf-8'))
    assert report['passed'] and tests['exit_code']==0
    assert 'Ran 224 tests' in (evidence/'fresh-unit-tests.log').read_text(encoding='utf-8')
    files={}
    for name,digest in tested['files'].items():
        raw=(candidate/name).read_bytes();assert hashlib.sha256(raw).hexdigest()==digest
        files[name]=raw
    files['README.md']=(ROOT/'README.md').read_bytes()
    guide='새폴더_설치실행검증_v14.md'
    files['docs/'+guide]=(ROOT/'docs'/guide).read_bytes()
    for name in ['verify_clean_candidate.py','package_clean_candidate.py']:
        files['tools/'+name]=(ROOT/'tools'/name).read_bytes()
    for file in evidence.iterdir():
        if file.is_file(): files['verification/'+file.name]=file.read_bytes()
    files['verification/tested-source-manifest.json']=(candidate/'submission-manifest.json').read_bytes()
    screenshot=output/'fresh-install-start.png'
    if screenshot.exists(): files['verification/'+screenshot.name]=screenshot.read_bytes()
    assert not any(name.split('/')[0] in ('data','.venv','output','config.json') or '__pycache__' in name.split('/') for name in files)
    # Runtime byte-for-byte equality with the tested copy; documentation/report additions are separate.
    assert all(hashlib.sha256(raw).hexdigest()==tested['files'][name] for name,raw in files.items() if name.startswith(('app/','static/','sample_data/','reference_data/','wheels/')))
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'wheel_target':'Windows x64 CPython 3.12','tested_python':report['python'],
              'excluded':['config.json','data/','.venv/','output/','__pycache__/'],'runtime_matches_tested_copy':True,
              'scope':report['scope_notice'],'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in sorted(files.items())}}
    files['submission-manifest.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    target=output/'서무비서_제출후보_v14_설치파일포함.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,raw in sorted(files.items()): z.writestr('서무비서/'+name,raw)
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for name,digest in manifest['files'].items(): assert hashlib.sha256(z.read('서무비서/'+name)).hexdigest()==digest
    (output/'새폴더_설치실행_검증결과.md').write_bytes((ROOT/'docs'/guide).read_bytes())
    summary={'archive':target.name,'archive_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'bytes':target.stat().st_size,'files':len(files),
             'models':[{'model':r['response_model'],'passed':r['passed'],'seconds':r['elapsed_seconds']} for r in report['model_runs']],
             'travel_runs':report['travel_runs'],'unit_tests':224,'runtime_matches_tested_copy':True,'scope':report['scope_notice']}
    (output/'새폴더_설치검증_묶음정보.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'files':len(files),'bytes':target.stat().st_size,'sha256':summary['archive_sha256']},indent=2))


if __name__=='__main__': main()
