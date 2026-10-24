"""Build a clean, relocatable submission, with registered sources separate from model weights."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import zipfile
from datetime import datetime,timezone
from contextlib import closing

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def export_knowledge(root,dest,manual_source_ids=()):
    source=root/'data/folders.db'
    with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as c:
        rows=c.execute('SELECT enabled,payload FROM knowledge_sources ORDER BY id').fetchall()
    records=[];selected=set(manual_source_ids);exported_manuals=set()
    for enabled,payload in rows:
        row=json.loads(payload)
        manual=row.get('reference_kind')=='system_manual'
        if manual:
            if row['id'] not in selected:continue
            if row['kind']!='업무편람':raise ValueError('Invalid manual reference kind')
            exported_manuals.add(row['id'])
        elif row['kind'] not in ('법령·규정','기관 지침'):continue
        original=Path(row['path'])
        if not original.is_file() or sha(original)!=row['sha256']:
            raise ValueError('Cannot export missing/changed source: '+row['id'])
        relative=(f"submission-data/manuals/{row['sha256']}.pdf" if manual else
                  f"submission-data/sources/{row['library_id']}/{row['sha256']}{original.suffix.lower()}")
        target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
        keep=('id','library_id','file_id','title','sha256','units','limited','kind','institution','effective_date','registered_at','official')
        entry={k:row[k] for k in keep if k in row}
        if manual:
            entry.update({k:row[k] for k in ('reference_kind','system','page_count','indexed_pages','page_coverage','scan_profile','local_only') if k in row})
        entry.update(asset=relative,enabled=int(enabled),library_name='e-사람 매뉴얼 · 전체 페이지' if manual else '등록 법령·지침 · 제출 사본')
        records.append(entry)
    if exported_manuals!=selected:raise ValueError('Selected manual source is missing or is not a system manual')
    if not records:raise ValueError('No registered law/guidance sources')
    snapshot={}
    monitor=root/'data/regulation-monitor.db'
    if monitor.exists():
        with closing(sqlite3.connect(monitor.resolve().as_uri()+'?mode=ro',uri=True)) as c:
            c.row_factory=sqlite3.Row
            c.execute('BEGIN')
            active=c.execute('SELECT * FROM active WHERE id=1').fetchone()
            snapshot=dict(active=dict(active) if active else None,
                runs=[dict(r) for r in c.execute("SELECT * FROM runs WHERE status!='running'")],
                changes=[dict(r) for r in c.execute('SELECT * FROM changes')])
        # All source evidence is public; exclude private affected-trip records if introduced later.
        if snapshot['changes']:
            raise ValueError('Pending regulation changes require a separately reviewed export')
        for row in snapshot['runs']:
            result=json.loads(row['result_json'])
            public=('changes','complete','errors','manifest_sha256','records','status','summary','verified_through')
            row['result_json']=json.dumps({k:result[k] for k in public if k in result},ensure_ascii=False)
        save(dest/'submission-data/regulation-snapshot.json',snapshot)
    bundle=dict(format=1,created_at=datetime.now(timezone.utc).isoformat(),sources=records,
                model_independent=True,excluded=['private travel/education records','folder AI runs','watches','work experiences','local config','model weights'])
    if selected:bundle['selected_manual_source_ids']=sorted(selected)
    if snapshot:
        bundle['regulation_snapshot']=dict(asset='submission-data/regulation-snapshot.json',sha256=sha(dest/'submission-data/regulation-snapshot.json'))
        hashes={record['sha256'] for row in snapshot['runs'] for record in json.loads(row['result_json']).get('records',[]) if 'sha256' in record}
        objects=[]
        for digest in sorted(hashes):
            source=root/'data/regulation-monitor/objects'/digest
            if not source.is_file() or sha(source)!=digest:raise ValueError('Missing official check evidence object '+digest)
            asset='submission-data/regulation-objects/'+digest
            target=dest/asset;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
            objects.append(dict(asset=asset,sha256=digest))
        bundle['regulation_objects']=objects
    save(dest/'submission-data/knowledge.json',bundle)
    return bundle


def build(dest,wheels,root=ROOT,manual_source_ids=()):
    dest=Path(dest).resolve();root=Path(root).resolve();wheels=Path(wheels).resolve()
    if dest.exists() or dest==root or dest.is_relative_to(root):
        raise ValueError('Use a new destination outside the source application')
    if not list(wheels.glob('*.whl')):raise ValueError('Wheel files are required')
    dest.mkdir(parents=True)
    ignored=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo')
    for directory in ('app','static','sample_data','reference_data','tests'):
        shutil.copytree(root/directory,dest/directory,ignore=ignored)
    shutil.copytree(root/'tools',dest/'tools',ignore=shutil.ignore_patterns('__pycache__','*.pyc','build_public_demo.py'))
    for name in ('requirements.txt','requirements-travel.lock.txt','config.example.json','install-submission.bat','start-submission.bat'):
        shutil.copyfile(root/name,dest/name)
    shutil.copytree(wheels,dest/'wheels')
    bundle=export_knowledge(root,dest,manual_source_ids) if manual_source_ids else export_knowledge(root,dest)
    release='53'
    guide=root/'먼저읽기.txt'
    for version in ('69','68','67','66','64','61','57','55','54','53','45','44'):
        candidate=root/f'docs/다른PC_제출패키지_구동안내_v{version}.txt'
        if candidate.exists():guide=candidate;release=version;break
    if guide.exists():shutil.copyfile(guide,dest/'먼저읽기.txt')
    (dest/'검증결과바로가기.txt').write_text(
        f'실제 검증 결과는 verification/서무비서_다른PC_검증보고서_v{release}.txt 및 '
        f'verification/최종검증요약_v{release}.json에서 확인하세요. '
        '검증 결과는 archive --evidence 옵션으로 제출 아카이브에 동봉됩니다.\n',
        encoding='utf-8')
    manifest=dict(format=1,release_version='v'+release,created_at=datetime.now(timezone.utc).isoformat(),sources=len(bundle['sources']),
        target='Windows x64 CPython 3.12; model server installed separately',
        files={p.relative_to(dest).as_posix():sha(p) for p in sorted(dest.rglob('*')) if p.is_file()})
    save(dest/'submission-manifest.json',manifest)
    return manifest


def archive(candidate,output,evidence=None):
    candidate=Path(candidate);output=Path(output)
    manifest=json.loads((candidate/'submission-manifest.json').read_text(encoding='utf-8'))
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():raise ValueError('Archive already exists')
    proof={}
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,digest in manifest['files'].items():
            p=candidate/name
            if sha(p)!=digest:raise ValueError('Tested source was modified: '+name)
            z.write(p,'서무비서/'+name)
        z.write(candidate/'submission-manifest.json','서무비서/submission-manifest.json')
        if evidence:
            for p in sorted(Path(evidence).rglob('*')):
                if p.is_file():
                    name=p.relative_to(evidence).as_posix();proof[name]=sha(p)
                    z.write(p,'서무비서/verification/'+name)
            z.writestr('서무비서/verification-manifest.json',json.dumps(proof,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(output) as z:
        if z.testzip():raise ValueError('Archive CRC failure')
        for name,digest in manifest['files'].items():
            if hashlib.sha256(z.read('서무비서/'+name)).hexdigest()!=digest:raise ValueError('Archive hash mismatch')
        for name,digest in proof.items():
            if hashlib.sha256(z.read('서무비서/verification/'+name)).hexdigest()!=digest:raise ValueError('Evidence hash mismatch')
    return dict(archive=output.name,sha256=sha(output),bytes=output.stat().st_size,files=len(manifest['files']),sources=manifest['sources'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dest',type=Path,required=True)
    p.add_argument('--wheels',type=Path);p.add_argument('--archive',type=Path);p.add_argument('--evidence',type=Path)
    p.add_argument('--manual-source-id',action='append',default=[],help='Explicitly approved system manual source ID to include')
    args=p.parse_args()
    result=archive(args.dest,args.archive,args.evidence) if args.archive else build(args.dest,args.wheels,manual_source_ids=args.manual_source_id)
    print(json.dumps({k:v for k,v in result.items() if k!='files'},ensure_ascii=False,indent=2))
