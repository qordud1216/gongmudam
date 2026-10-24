"""독립 DB의 출장정산 API. 기존 서무 자료를 변경하지 않는 추가 모듈."""
from __future__ import annotations

import csv
import html
import hashlib
import io
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from .search import BM25
from .travel_engine import LABELS, evaluate, extract_situation, parse_evidence
from .travel_models import CalculationInput, Decision, EvidenceImport, IssueResolution, RuleCreate, Situation, TripCreate, Version
from . import travel_calculator as calculator
from . import travel_rates,travel_validity,regulation_registry
from .travel_models import LegalPackUpdate
from .travel_models import DocumentConfirmation, TaskCreate, TaskChange, DemoPrepare
from .travel_models import OrganizationCreate, OrganizationChange
from .travel_models import RuleReview
from . import travel_provenance
from . import travel_forms
from .travel_models import TripChange
from . import travel_files
from . import travel_package
from . import travel_workflow
from . import travel_journey
from .travel_models import StageNote, StageNoteTask
from . import travel_demo

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "travel.db"
router = APIRouter(prefix="/api/travel", tags=["출장정산 Demo 1"])

PACKS = [("COMMON", "정부 공통", "공통"), ("NATIONAL", "국가공무원", "신분"),
         ("LOCAL", "지방공무원", "신분"), ("FIRE", "소방공무원", "직군"),
         ("GG", "경기도", "지역"), ("CITY", "가람시청", "기관"), ("FIRE_GG", "가람소방서", "기관")]
LEGAL_PACKS=[('LEGAL_NATIONAL','국가 국내여비 · 공식 출처 확인','법령'),('LEGAL_GG','경기도 소속 · 공식 출처 확인','조례')]
ORGS = [
    ("demo-city", "모의 가람시청", "지방자치단체", "경기도", "지방공무원", ["COMMON", "LOCAL", "GG", "CITY"]),
    ("demo-national", "모의 중앙행정기관", "중앙행정기관", "세종", "국가공무원", ["COMMON", "NATIONAL"]),
    ("demo-fire", "모의 가람소방서", "소방기관", "경기도", "소방공무원", ["COMMON", "NATIONAL", "FIRE", "GG", "FIRE_GG"]),
]
LEGAL_ORGS=[
 ('national-general','국가기관 · 국가공무원 공통기준','중앙행정기관','전국','국가공무원',['LEGAL_NATIONAL']),
 ('gg-province','경기도 소속 · 지방공무원','도 소속기관','경기도','지방공무원',['LEGAL_NATIONAL','LEGAL_GG']),
 ('gg-fire','경기도 소방기관 · 소방공무원','도 소방기관','경기도','소방공무원',['LEGAL_NATIONAL','LEGAL_GG'])
]


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize():
    with db() as c:
        c.executescript((ROOT / "app" / "travel_schema.sql").read_text(encoding="utf-8"))
        c.executemany("INSERT OR IGNORE INTO rule_packs VALUES (?,?,?)", PACKS+LEGAL_PACKS)
        for org in ORGS+LEGAL_ORGS:
            c.execute("INSERT OR IGNORE INTO organizations VALUES (?,?,?,?,?,?)", (*org[:5], dumps(org[5])))
        for pack, name, layer in PACKS:
            text = ("[합성 시연자료] 출장명령·기간과 거래내역을 대조하고 공식 영수증을 준비한다. "
                    "거래 후보는 실제 지급액이 아니며 실제 규정·한도·감액 조건은 담당자가 확인한다.")
            if layer == "기관":
                text += " 정산서 초안과 증빙 목록을 기관의 기존 출장·회계시스템에 입력한다."
            c.execute("INSERT OR IGNORE INTO travel_rules VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (f"sample-{pack}", pack, f"{name} 출장정산 안내(가상)", "시연 제1항", text,
                       "2026-01-01", None, "demo-1", "synthetic", now()))


def get_case(c, case_id):
    row = c.execute("SELECT * FROM travel_cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        raise HTTPException(404, "출장 건을 찾을 수 없습니다.")
    result = dict(row)
    for key in ("profile_snapshot", "trip_json", "rule_snapshot", "parse_issues"):
        result[key] = json.loads(result[key])
    return result


def event(c, case_id, kind, payload):
    c.execute("INSERT INTO travel_events(case_id,event_type,payload,created_at) VALUES (?,?,?,?)",
              (case_id, kind, dumps(payload), now()))


def bump(c, case_id, version):
    result = c.execute("UPDATE travel_cases SET version=version+1,updated_at=? WHERE id=? AND version=?",
                       (now(), case_id, version))
    if result.rowcount != 1:
        raise HTTPException(409, "다른 변경이 있습니다. 출장 목록에서 다시 열어 주세요.")


def applicable_rules(c, packs, start, end):
    marks = ",".join("?" for _ in packs)
    return travel_provenance.attach_reviews(c,[dict(r) for r in c.execute(
        f"SELECT * FROM travel_rules WHERE pack_id IN ({marks}) AND effective_date<=? "
        "AND (expiry_date IS NULL OR expiry_date>?) ORDER BY pack_id,title,version",
        (*packs, end, start))])


def registered_org(c, organization_id):
    row=c.execute('SELECT * FROM organizations WHERE id=?',(organization_id,)).fetchone()
    if not row: raise HTTPException(404,'기관이 없습니다.')
    if not c.execute('SELECT 1 FROM travel_organization_settings WHERE organization_id=?',(organization_id,)).fetchone():
        raise HTTPException(422,'직접 등록한 기관의 전용 규정 원문만 관리합니다.')
    return row


@router.get('/organizations/{organization_id}/form-templates')
def list_form_templates(organization_id: str):
    with db() as c:
        row=registered_org(c,organization_id)
        org=organization_view(c,row)
        templates=[travel_forms.metadata(r) for r in c.execute('SELECT * FROM travel_form_templates WHERE organization_id=? ORDER BY name,effective_date,version,id',(organization_id,))]
        return {'templates':templates,'required_forms':org['settings']['required_forms'],'tokens':travel_forms.TOKENS,
                'notice':'UTF-8 TXT 채움 서식입니다. HWP·DOCX·PDF 원본 양식 채우기는 지원하지 않습니다. 새 출장부터 서식 사본을 보존합니다.'}


@router.post('/organizations/{organization_id}/form-templates',status_code=201)
async def upload_form_template(organization_id: str, file: UploadFile=File(...), name: str=Form(...), version: str=Form(...), effective_date: date=Form(...), expiry_date: date|None=Form(None)):
    with db() as c: registered_org(c,organization_id)
    try:
        metadata=travel_forms.TemplateMetadata(name=name,version=version,effective_date=effective_date,expiry_date=expiry_date)
        raw=await file.read(travel_forms.MAX_BYTES+1)
        filename,text=travel_forms.read_template(raw,file.filename or '')
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    finally: await file.close()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        org=organization_view(c,registered_org(c,organization_id))
        if metadata.name not in org['settings']['required_forms']: raise HTTPException(422,'기관 준비서식 목록에 먼저 같은 서식명을 저장하세요.')
        if c.execute('SELECT 1 FROM travel_form_templates WHERE organization_id=? AND name=? AND version=?',(organization_id,metadata.name,metadata.version)).fetchone():
            raise HTTPException(409,'같은 서식명·버전이 있습니다. 새 판본은 다른 버전으로 등록하세요.')
        key=uuid.uuid4().hex
        c.execute('INSERT INTO travel_form_templates VALUES (?,?,?,?,?,?,?,?,?,?)',(key,organization_id,metadata.name,metadata.version,str(metadata.effective_date),str(metadata.expiry_date) if metadata.expiry_date else None,filename,raw,hashlib.sha256(raw).hexdigest(),now()))
        return travel_forms.metadata(c.execute('SELECT * FROM travel_form_templates WHERE id=?',(key,)).fetchone())


@router.get('/organizations/{organization_id}/form-templates/{template_id}/original')
def original_form_template(organization_id: str, template_id: str):
    with db() as c:
        row=c.execute('SELECT * FROM travel_form_templates WHERE id=? AND organization_id=?',(template_id,organization_id)).fetchone()
        if not row: raise HTTPException(404,'기관 서식이 없습니다.')
        if hashlib.sha256(row['original']).hexdigest()!=row['sha256']: raise HTTPException(409,'서식 원본 해시가 다릅니다. 복구·재검수가 필요합니다.')
        return Response(row['original'],media_type='text/plain',headers={'Content-Disposition':f'attachment; filename="form-{template_id}.txt"','X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})


@router.get('/organizations/{organization_id}/rule-sources')
def list_rule_sources(organization_id: str):
    with db() as c:
        registered_org(c,organization_id)
        sources=[travel_provenance.source_view(r) for r in c.execute('SELECT id,organization_id,metadata_json,created_at FROM travel_rule_sources WHERE organization_id=? ORDER BY created_at,id',(organization_id,))]
        org=c.execute('SELECT rule_packs FROM organizations WHERE id=?',(organization_id,)).fetchone()
        packs=json.loads(org['rule_packs'])
        rules=[dict(r) for r in c.execute('SELECT * FROM travel_rules WHERE pack_id=? ORDER BY created_at,id',(packs[0],))]
        return {'sources':sources,'rules':travel_provenance.attach_reviews(c,rules),'notice':'이력의 검토자명은 사용자 입력이며 인증된 신원을 의미하지 않습니다. 원문 대조는 공식 계산팩 승인과 구분합니다.'}


@router.post('/organizations/{organization_id}/rule-sources',status_code=201)
async def upload_rule_source(organization_id: str, file: UploadFile=File(...), title: str=Form(...), issuer: str=Form(...), source_url: str=Form('')):
    with db() as c: registered_org(c,organization_id)
    try:
        raw=await file.read(travel_provenance.MAX_BYTES+1)
        metadata=travel_provenance.validate_source(raw,file.filename or '',title,issuer,source_url)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    finally: await file.close()
    with db() as c:
        c.execute('BEGIN IMMEDIATE');registered_org(c,organization_id)
        duplicate=c.execute('SELECT id,organization_id,metadata_json,created_at FROM travel_rule_sources WHERE organization_id=? AND sha256=?',(organization_id,metadata['sha256'])).fetchone()
        if duplicate: return {'source':travel_provenance.source_view(duplicate),'duplicate':True}
        key=uuid.uuid4().hex
        c.execute('INSERT INTO travel_rule_sources VALUES (?,?,?,?,?,?)',(key,organization_id,dumps(metadata),raw,metadata['sha256'],now()))
        row=c.execute('SELECT id,organization_id,metadata_json,created_at FROM travel_rule_sources WHERE id=?',(key,)).fetchone()
        return {'source':travel_provenance.source_view(row),'duplicate':False}


@router.get('/organizations/{organization_id}/rule-sources/{source_id}/original')
def original_rule_source(organization_id: str, source_id: str):
    with db() as c:
        row=c.execute('SELECT * FROM travel_rule_sources WHERE id=? AND organization_id=?',(source_id,organization_id)).fetchone()
        if not row: raise HTTPException(404,'기관에 속한 원문이 없습니다.')
        metadata=travel_provenance.source_view(row)
        if hashlib.sha256(row['original']).hexdigest()!=metadata['sha256'] or metadata['sha256']!=row['sha256']:
            raise HTTPException(409,'원문 해시가 보존 기록과 다릅니다. 복구·재검수가 필요합니다.')
        return Response(row['original'],media_type=metadata['media_type'],headers={'Content-Disposition':f'attachment; filename="rule-source-{source_id}{metadata["extension"]}"','X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})


@router.post('/rules/{rule_id}/reviews',status_code=201)
def append_rule_review(rule_id: str, body: RuleReview):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        rule=c.execute('SELECT * FROM travel_rules WHERE id=?',(rule_id,)).fetchone()
        if not rule: raise HTTPException(404,'등록된 조항이 없습니다.')
        source=c.execute('SELECT * FROM travel_rule_sources WHERE id=?',(body.source_id,)).fetchone()
        if not source: raise HTTPException(404,'원문이 없습니다.')
        org=registered_org(c,source['organization_id'])
        if rule['pack_id'] not in json.loads(org['rule_packs']): raise HTTPException(422,'원문과 조항은 같은 기관에 속해야 합니다.')
        metadata=json.loads(source['metadata_json'])
        if hashlib.sha256(source['original']).hexdigest()!=source['sha256'] or metadata['sha256']!=source['sha256']:
            raise HTTPException(409,'원문 해시가 보존 기록과 다릅니다. 이력을 추가하기 전에 복구·재검수하세요.')
        latest=c.execute('SELECT max(revision) AS revision FROM travel_rule_reviews WHERE rule_id=?',(rule_id,)).fetchone()['revision'] or 0
        if body.revision!=latest: raise HTTPException(409,'검수 이력이 변경되었습니다. 새로 조회한 후 기록하세요.')
        c.execute('INSERT INTO travel_rule_reviews VALUES (?,?,?,?,?,?)',(uuid.uuid4().hex,rule_id,latest+1,body.source_id,dumps(body.model_dump(exclude={'revision','source_id'})),now()))
        return travel_provenance.attach_reviews(c,[dict(rule)])[0]


def organization_view(c, row):
    org = dict(row)
    org['rule_packs'] = json.loads(org['rule_packs'])
    org['calculation_available'] = calculator.select_pack(org['id']) is not None
    settings = c.execute('SELECT * FROM travel_organization_settings WHERE organization_id=?', (org['id'],)).fetchone()
    org['profile_kind'] = 'registered' if settings else ('official' if org['calculation_available'] else 'synthetic')
    org['settings'] = json.loads(settings['settings_json']) if settings else {'work_pattern':'일반근무','note':'','required_forms':[]}
    org['settings_revision'] = settings['revision'] if settings else 0
    return org


@router.post('/organizations', status_code=201)
def register_organization(body: OrganizationCreate):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM organizations WHERE name=? AND region=?', (body.name,body.region)).fetchone():
            raise HTTPException(409,'같은 이름·지역의 기관이 등록되어 있습니다.')
        key=uuid.uuid4().hex; pack='ORG_'+key; stamp=now()
        c.execute('INSERT INTO rule_packs VALUES (?,?,?)',(pack,body.name+' · 기관 등록자료','기관'))
        c.execute('INSERT INTO organizations VALUES (?,?,?,?,?,?)',(key,body.name,body.organization_type,body.region,body.personnel_type,dumps([pack])))
        settings=body.model_dump(include={'work_pattern','note','required_forms'})
        c.execute('INSERT INTO travel_organization_settings VALUES (?,?,?,?,?)',(key,1,dumps(settings),stamp,stamp))
        return organization_view(c,c.execute('SELECT * FROM organizations WHERE id=?',(key,)).fetchone())


@router.patch('/organizations/{organization_id}/settings')
def change_organization_settings(organization_id: str, body: OrganizationChange):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM organizations WHERE id=?',(organization_id,)).fetchone()
        if not row: raise HTTPException(404,'기관이 없습니다.')
        if not c.execute('SELECT 1 FROM travel_organization_settings WHERE organization_id=?',(organization_id,)).fetchone():
            raise HTTPException(422,'기본 제공 프로필은 이 화면에서 수정하지 않습니다.')
        changed=c.execute('UPDATE travel_organization_settings SET revision=revision+1,settings_json=?,updated_at=? WHERE organization_id=? AND revision=?',
                          (dumps(body.model_dump(exclude={'revision'})),now(),organization_id,body.revision))
        if changed.rowcount!=1: raise HTTPException(409,'다른 설정 변경이 있습니다. 기관을 다시 선택하세요.')
        return organization_view(c,row)


@router.get('/organizations/{organization_id}/diagnostics')
def organization_diagnostics(organization_id: str, start_date: date, end_date: date):
    if end_date<start_date: raise HTTPException(422,'종료일이 시작일보다 빠릅니다.')
    with db() as c:
        row=c.execute('SELECT * FROM organizations WHERE id=?',(organization_id,)).fetchone()
        if not row: raise HTTPException(404,'기관이 없습니다.')
        org=organization_view(c,row); pack=calculator.select_pack(organization_id)
        found=applicable_rules(c,org['rule_packs'],str(start_date),str(end_date)) if not pack else rules(organization_id,start_date,end_date,'')['rules']
        findings=[]
        if not pack: findings.append('검증된 계산팩이 없습니다. 기관명·지역·직군만으로 다른 기관 기준을 자동 적용하지 않습니다.')
        elif not travel_validity.assess(pack,start_date,end_date)['allowed']: findings.append('선택 기간은 계산팩의 확인 범위를 벗어납니다. 최신 원문 재확인이 필요합니다.')
        elif travel_validity.assess(pack,start_date,end_date)['is_estimate']: findings.append('예정 출장의 사전산정 범위입니다. 여행 종료 후 실제 내역과 최신 기준을 다시 확인하세요.')
        if not found: findings.append('선택 기간에 조회되는 규정 조항이 없습니다.')
        if any(r['status']!='source_verified' for r in found): findings.append('합성·미검증 등록자료가 있습니다. 계산 기준이나 법적 적합성을 인증하지 않습니다.')
        if org['profile_kind']=='registered':
            if any(not r.get('user_review') for r in found): findings.append('원문 연결·대조 이력이 없는 조항이 있습니다.')
            if any(r.get('user_review',{}).get('outcome')=='needs_revision' for r in found): findings.append('최근 원문 대조에서 보완 필요로 기록한 조항이 있습니다.')
        partial=[r['id'] for r in found if r['effective_date']>str(start_date) or (r.get('expiry_date') and r['expiry_date']<=str(end_date))]
        if partial: findings.append('출장기간 일부에만 적용되는 조항이 있습니다. 시행·종료일을 나누어 검토하세요.')
        overlaps=[]
        for i,a in enumerate(found):
            for b in found[i+1:]:
                if (a['pack_id'],a['title'],a['article'])==(b['pack_id'],b['title'],b['article']) and max(a['effective_date'],b['effective_date'])<min(a.get('expiry_date') or '9999-12-31',b.get('expiry_date') or '9999-12-31'):
                    overlaps.append([a['id'],b['id']])
        if overlaps: findings.append('같은 규정·조항의 적용 기간이 중복됩니다. 버전을 자동 선택하지 않습니다.')
        try: form_bindings=travel_forms.bindings(c,org,str(start_date),str(end_date)) if org['profile_kind']=='registered' else []
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc
        if any(b['status']!='ready' for b in form_bindings): findings.append('준비서식 파일 누락·버전 중복·기간 일부 적용을 확인하세요. 해당 서식은 자동 채우지 않습니다.')
        return {'organization':org,'start_date':str(start_date),'end_date':str(end_date),'rules':found,'partial_rule_ids':partial,'overlaps':overlaps,'findings':findings,
                'form_bindings':[{k:v for k,v in b.items() if k!='template_text'} for b in form_bindings],
                'calculation_scope':{'coverage_start':pack['coverage_start'],'verified_through':pack['verified_through']} if pack else None,
                'notice':'기관 설정은 새 출장에 사본으로 저장됩니다. TXT 자동 채움 서식은 아래 기관별 서식 메뉴에서 등록하고, 다른 원문 양식은 기존 공용 자료 관리에서 보관하세요.'}


def detail(c, case_id):
    case = get_case(c, case_id)
    rows = [dict(r) for r in c.execute("SELECT * FROM travel_transactions WHERE case_id=? ORDER BY transaction_date,transaction_time,id", (case_id,))]
    result = evaluate(case["trip_json"], rows, case["rule_snapshot"], case["parse_issues"])
    for form in case['profile_snapshot'].get('settings',{}).get('required_forms',[]):
        result['next_actions'].append('기관 준비서식 확인: '+form+' (첨부·승인 여부는 담당자 대조 필요)')
    documents=[]
    for row in c.execute('SELECT id,filename,media_type,sha256,length(original) AS size,extraction,suggested_text,confirmed_text,confirmation_reason,created_at,confirmed_at FROM travel_documents WHERE case_id=? ORDER BY created_at,id',(case_id,)):
        document=dict(row); document['extraction']=json.loads(document['extraction'])
        document['original_url']=f'/api/travel/cases/{case_id}/documents/{document["id"]}/original'
        document['preview_url']=f'/api/travel/cases/{case_id}/documents/{document["id"]}/preview' if document['media_type'].startswith('image/') else None
        documents.append(document)
    links={}
    for row in c.execute('SELECT dt.transaction_id,dt.document_id FROM travel_document_transactions dt JOIN travel_documents d ON dt.document_id=d.id WHERE d.case_id=?',(case_id,)):
        links.setdefault(row['transaction_id'],[]).append(row['document_id'])
    for transaction in result['transactions']: transaction['document_ids']=links.get(transaction['id'],[])
    unconfirmed=sum(not d['confirmed_at'] for d in documents)
    if unconfirmed:
        message=f'첨부파일 {unconfirmed}건의 원본과 추출 후보를 확인하세요. 확인 전에는 거래로 반영되지 않습니다.'
        result['findings'].append({'code':'DOCUMENT_UNCONFIRMED','message':message})
        result['next_actions'].insert(0,message)
    events = [dict(r) for r in c.execute("SELECT * FROM travel_events WHERE case_id=? ORDER BY id DESC", (case_id,))]
    for item in events:
        item["payload"] = json.loads(item["payload"])
    saved=c.execute('SELECT * FROM travel_calculations WHERE case_id=? ORDER BY case_version DESC,created_at DESC LIMIT 1',(case_id,)).fetchone()
    calc=None
    if saved:
        calc={**dict(saved),'result':json.loads(saved['result_json']),'inputs':json.loads(saved['inputs_json']),
              'stale':saved['case_version']!=case['version']}
        for key in ('result_json','inputs_json','rulepack_snapshot'): calc.pop(key,None)
        training=calc['inputs'].get('training')
        if training and not calc['stale'] and calc['result']['status']=='calculated_for_review':
            removed={'EMPTY'}
            if training['residential'] or 'lodging' in training['zero_items']: removed.add('LODGING')
            removed_messages={f['message'] for f in result['findings'] if f['code'] in removed}
            result['findings']=[f for f in result['findings'] if f['code'] not in removed]
            message='교육기관 안내문·입교/수료 확인·청구서와 실제 비용 발생·직접 지급 내역을 최종 대조하세요.'
            result['findings'].append({'code':'TRAINING_DOCUMENT','message':message})
            result['next_actions']=[message]+[m for m in result['next_actions'] if m not in removed_messages]
    legal=c.execute('SELECT snapshot FROM travel_case_legalpacks WHERE case_id=?',(case_id,)).fetchone()
    pack=json.loads(legal['snapshot']) if legal else None
    holds=regulation_registry.holds(pack,case['trip_json'])
    if holds:
        if calc:calc.update(stale=True,stale_reason=holds[0]['message'])
        result['findings'].append({'code':'REGULATION_CHANGED','message':holds[0]['message']})
        result['next_actions'].insert(0,holds[0]['message'])
    tasks=[dict(r) for r in c.execute('SELECT * FROM travel_tasks WHERE case_id=? ORDER BY created_at,id',(case_id,))]
    workflow=c.execute('SELECT revision FROM travel_case_workflow WHERE case_id=?',(case_id,)).fetchone()
    origin=c.execute('SELECT scenario_id,expected_json FROM travel_case_origins WHERE case_id=?',(case_id,)).fetchone()
    view={**case, "review": result, "events": events, "documents":documents, "tasks":tasks,
            "workflow_revision":workflow['revision'] if workflow else 0, "demo": pack is None,
            'calculation':calc,'regulatory_hold':holds,'legal_profile':pack['profile'] if pack else None,
            'calculation_table':travel_rates.table_view(pack)}
    view['data_origin']='synthetic_demo' if origin else 'user_input'
    if view['calculation_table'] and view['calculation_table']['available']:
        view['calculation_table']['basis']=calculator.basis(pack,['T1','T2'] if pack.get('domestic_table') else ['N3','T2'])
    latest=calculator.select_pack(case['organization_id'])
    view['legal_update']={'available':bool(pack and latest and pack.get('bundle_sha256')!=latest.get('bundle_sha256')),
        'saved_version':pack['version'] if pack else None,'latest_version':latest['version'] if latest else None,
        'saved_verified_through':pack['verified_through'] if pack else None,'latest_verified_through':latest['verified_through'] if latest else None}
    trip_change=next((e for e in events if e['event_type'] in ('TRIP_CHANGED','LEGAL_PACK_UPDATED','LEGAL_PACK_AUTO_REFRESHED')),None)
    view['calculation_inputs_reset']=bool(trip_change and (not calc or trip_change['payload']['to_version']>calc['case_version']))
    if origin:
        view['scenario_id']=origin['scenario_id']
        view['demo_report']=travel_demo.report(view,json.loads(origin['expected_json']))
    return view


@router.get("/bootstrap")
def bootstrap():
    with db() as c:
        orgs = [organization_view(c,r) for r in c.execute("SELECT * FROM organizations ORDER BY id")]
        return {"organizations": orgs, "packs": [dict(r) for r in c.execute("SELECT * FROM rule_packs")],
                "mode": "offline_deterministic", "schema_version": 1,
                "notice": "공식 출처를 확인한 국가·경기도 소속 일반출장 계산과 기존 모의 시연을 구분합니다. 최종 지급은 담당자 검토가 필요합니다."}


@router.post("/extract")
def extract(body: Situation):
    return extract_situation(body.text)


@router.get("/rules")
def rules(organization_id: str = "demo-city", start_date: date = date(2026, 10, 15),
          end_date: date = date(2026, 10, 17), q: str = "출장 정산 증빙"):
    if end_date < start_date:
        raise HTTPException(422, "종료일이 시작일보다 빠릅니다.")
    with db() as c:
        org = c.execute("SELECT * FROM organizations WHERE id=?", (organization_id,)).fetchone()
        if not org:
            raise HTTPException(404, "기관이 없습니다.")
        pack=calculator.select_pack(organization_id)
        if pack:
            found=[r for r in calculator.searchable_rules(pack) if r['effective_date']<=str(start_date)] if travel_validity.assess(pack,start_date,end_date)['allowed'] else []
        else:
            found=applicable_rules(c, json.loads(org['rule_packs']), str(start_date), str(end_date))
        if q.strip():
            ranked = BM25([r["title"] + " " + r["text"] for r in found]).top(q, k=len(found))
            found = [{**found[i], "score": round(score, 3)} for i, score in ranked]
        return {"rules": found, "retrieval": "metadata_filter_then_bm25", "demo": pack is None}


@router.post("/rules", status_code=201)
def add_rule(body: RuleCreate):
    with db() as c:
        if not c.execute("SELECT 1 FROM rule_packs WHERE id=?", (body.pack_id,)).fetchone():
            raise HTTPException(422, "존재하지 않는 규정팩입니다.")
        if body.pack_id.startswith('LEGAL_'):
            raise HTTPException(422,'공식 계산팩은 출처 검수한 배포 파일로 관리합니다. 사용자 등록자료로 계산 기준을 덮어쓸 수 없습니다.')
        key = uuid.uuid4().hex
        c.execute("INSERT INTO travel_rules VALUES (?,?,?,?,?,?,?,?,?,?)", (
            key, body.pack_id, body.title, body.article, body.text, str(body.effective_date),
            str(body.expiry_date) if body.expiry_date else None, body.version, body.status, now()))
        return {"id": key, "notice": "새 출장부터 조회됩니다. 기존 출장은 저장 당시 규정 사본을 유지합니다."}


@router.post("/cases", status_code=201)
def create_case(body: TripCreate):
    with db() as c:
        return create_case_row(c,body)


def prepare_trip_change(c,case_id,body):
    case=get_case(c,case_id)
    if body.version!=case['version']: raise HTTPException(409,'출장정보가 변경되었습니다. 다시 열어 변경 내용을 확인하세요.')
    if body.organization_id!=case['organization_id']: raise HTTPException(422,'저장한 출장의 소속기관은 변경할 수 없습니다. 다른 기관은 새 출장으로 작성하세요.')
    row=c.execute('SELECT * FROM organizations WHERE id=?',(case['organization_id'],)).fetchone()
    profile=organization_view(c,row);profile['work_pattern']=body.work_pattern
    if profile['profile_kind']=='registered':
        try: profile['form_bindings']=travel_forms.bindings(c,profile,str(body.start_date),str(body.end_date))
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    # Existing official cases retain the exact calculation bundle saved at creation.
    saved=c.execute('SELECT snapshot FROM travel_case_legalpacks WHERE case_id=?',(case_id,)).fetchone()
    pack=json.loads(saved['snapshot']) if saved else None
    if pack:
        profile['profile_kind']='official'
        profile['calculation_available']=True
        profile['rule_packs']=case['profile_snapshot']['rule_packs']
    rules=[r for r in calculator.searchable_rules(pack) if r['effective_date']<=str(body.start_date)] if pack else applicable_rules(c,profile['rule_packs'],str(body.start_date),str(body.end_date))
    trip=body.model_dump(mode='json',exclude={'version','reason','confirmed','preview_digest'})
    before={'trip':case['trip_json'],'profile':case['profile_snapshot'],'rules':case['rule_snapshot']}
    after={'trip':trip,'profile':profile,'rules':rules}
    if before==after: raise HTTPException(422,'변경된 출장정보나 기관 등록자료가 없습니다.')
    pending=[dict(r) for r in c.execute("SELECT id,decision,reason,category FROM travel_transactions WHERE case_id=? AND decision='include' ORDER BY id",(case_id,))]
    digest=hashlib.sha256(dumps({'case_id':case_id,'version':body.version,'before':before,'after':after,'reason':body.reason,'reset_transactions':pending}).encode()).hexdigest()
    differences=[{'field':key,'before':case['trip_json'].get(key),'after':value} for key,value in trip.items() if case['trip_json'].get(key)!=value]
    return {'before':before,'after':after,'changed_fields':differences,'reset_transactions':pending,'preview_digest':digest,
            'notice':'등록 기관의 현재 설정·규정·서식 사본을 다시 확인해 저장합니다. 포함 거래는 보류로 되돌리고 기존 계산은 재계산 대상으로 표시합니다. 증빙·이전 초안은 보존하며 공식 계산팩 버전은 유지합니다.'}


@router.post('/cases/{case_id}/change-preview')
def preview_trip_change(case_id: str,body: TripChange):
    with db() as c:
        c.execute('BEGIN')
        return prepare_trip_change(c,case_id,body)


@router.patch('/cases/{case_id}/trip')
def change_trip(case_id: str,body: TripChange):
    if not body.confirmed or not body.preview_digest: raise HTTPException(422,'변경 미리보기를 확인한 뒤 저장하세요.')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        preview=prepare_trip_change(c,case_id,body)
        if preview['preview_digest']!=body.preview_digest: raise HTTPException(409,'출장 또는 기관 등록자료가 달라졌습니다. 변경 미리보기를 다시 확인하세요.')
        bump(c,case_id,body.version)
        after=preview['after']
        c.execute('UPDATE travel_cases SET trip_json=?,profile_snapshot=?,rule_snapshot=? WHERE id=?',(dumps(after['trip']),dumps(after['profile']),dumps(after['rules']),case_id))
        c.execute("UPDATE travel_transactions SET decision='pending',reason=? WHERE case_id=? AND decision='include'",(('출장정보 변경으로 재검토 필요: '+body.reason)[:500],case_id))
        event(c,case_id,'TRIP_CHANGED',{'from_version':body.version,'to_version':body.version+1,'reason':body.reason,**preview})
        return detail(c,case_id)


def create_case_row(c,body):
    org=c.execute('SELECT * FROM organizations WHERE id=?',(body.organization_id,)).fetchone()
    if not org: raise HTTPException(422,'등록된 기관을 선택하세요.')
    profile=organization_view(c,org);profile['work_pattern']=body.work_pattern
    if profile['profile_kind']=='registered':
        try: profile['form_bindings']=travel_forms.bindings(c,profile,str(body.start_date),str(body.end_date))
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    trip=body.model_dump(mode='json');legal_pack=calculator.select_pack(body.organization_id)
    selected=[r for r in calculator.searchable_rules(legal_pack) if r['effective_date']<=str(body.start_date)] if legal_pack else applicable_rules(c,profile['rule_packs'],str(body.start_date),str(body.end_date))
    key=uuid.uuid4().hex;stamp=now()
    c.execute('INSERT INTO travel_cases(id,organization_id,profile_snapshot,trip_json,rule_snapshot,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',(key,body.organization_id,dumps(profile),dumps(trip),dumps(selected),stamp,stamp))
    if legal_pack:c.execute('INSERT INTO travel_case_legalpacks VALUES (?,?)',(key,dumps(legal_pack)))
    event(c,key,'CASE_CREATED',{'organization':profile['name'],'rule_ids':[r['id'] for r in selected]})
    return detail(c,key)


@router.get('/demo-scenarios')
def demo_scenarios():
    with db() as c:
        scenarios=[]
        for key in travel_demo.SCENARIOS:
            s=travel_demo.definition(key)
            previous=c.execute('SELECT case_id FROM travel_case_origins WHERE scenario_id=? ORDER BY created_at DESC,case_id DESC LIMIT 1',(key,)).fetchone()
            scenarios.append({k:s[k] for k in ('title','description','expected','steps')}|{'id':key,'existing_case_id':previous['case_id'] if previous else None})
        return {'scenarios':scenarios,'notice':'합성 시연자료를 생성합니다. 실제 지급·승인·기관 제출을 수행하지 않습니다.'}


@router.post('/demo-scenarios/{scenario_id}/prepare')
def prepare_demo(scenario_id: str,body: DemoPrepare):
    if scenario_id not in travel_demo.SCENARIOS: raise HTTPException(404,'시연 시나리오가 없습니다.')
    scenario=travel_demo.definition(scenario_id)
    try: fixtures=travel_demo.fixture_bytes(ROOT,scenario['fixtures'])
    except (OSError,ValueError) as exc: raise HTTPException(409,'합성 시연 이미지가 없거나 손상되었습니다. 설치 파일을 확인하세요.') from exc
    trip=TripCreate(**scenario['trip'])
    values=CalculationInput(version=1,**scenario['inputs']).model_dump(mode='json',exclude={'version'})
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        previous=c.execute('SELECT case_id FROM travel_case_origins WHERE scenario_id=? ORDER BY created_at DESC,case_id DESC LIMIT 1',(scenario_id,)).fetchone()
        if previous and not body.new_copy:
            saved=c.execute('SELECT id FROM travel_drafts WHERE case_id=? ORDER BY created_at DESC,id DESC LIMIT 1',(previous['case_id'],)).fetchone()
            return {**detail(c,previous['case_id']),'scenario_reused':True,'prepared_draft_id':saved['id'] if saved else None}
        case=create_case_row(c,trip);key=case['id'];stamp=now()
        c.execute('INSERT INTO travel_case_origins VALUES (?,?,?,?)',(key,scenario_id,dumps(scenario['expected']),stamp))
        parsed,issues=parse_evidence(scenario['text'],trip.start_date,trip.end_date,'receipt_text')
        inserted=0
        for row in parsed:
            cursor=c.execute('INSERT OR IGNORE INTO travel_transactions(id,case_id,transaction_date,transaction_time,merchant,amount,category,source_type,fingerprint,cancelled,decision,reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (uuid.uuid4().hex,key,row['transaction_date'],row['transaction_time'],row['merchant'],row['amount'],row['category'],'receipt_text',row['fingerprint'],row['cancelled'],
                 'pending' if scenario_id=='anomaly' else 'include','[합성 시연 자동 설정] 생성한 가상 거래·원본. 실제 사용자 검토 아님.'))
            inserted+=cursor.rowcount
        scenario['expected']['_initial_duplicates']=len(parsed)-inserted
        c.execute('UPDATE travel_case_origins SET expected_json=? WHERE case_id=?',(dumps(scenario['expected']),key))
        c.execute('UPDATE travel_cases SET parse_issues=? WHERE id=?',(dumps(issues),key))
        for fixture_key,raw in fixtures:
            filename,canonical=travel_demo.FIXTURES[fixture_key]
            record,_=parse_evidence(canonical,trip.start_date,trip.end_date,'receipt_text')
            transaction=c.execute('SELECT id FROM travel_transactions WHERE case_id=? AND fingerprint=?',(key,record[0]['fingerprint'])).fetchone()
            doc_id=uuid.uuid4().hex
            extraction=dict(engine='synthetic_fixture',text=canonical,pages=[dict(page=1,text=canonical)],warnings=['합성 시연용 고정 원문입니다. 이 예시 준비는 OCR 실행이나 실제 원본 진위 검증을 의미하지 않습니다.'])
            c.execute('INSERT INTO travel_documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(doc_id,key,filename,'image/png',hashlib.sha256(raw).hexdigest(),raw,dumps(extraction),canonical,canonical,'[합성 시연 자동 설정] 가상 원본·거래. 실제 사용자 대조 아님.',stamp,stamp))
            c.execute('INSERT INTO travel_document_transactions VALUES (?,?)',(doc_id,transaction['id']))
        event(c,key,'DEMO_PREPARED',{'scenario_id':scenario_id,'inserted':inserted,'duplicates_skipped':len(parsed)-inserted,'parse_issues':issues,'data_origin':'synthetic_demo'})
        view=detail(c,key);pack=json.loads(c.execute('SELECT snapshot FROM travel_case_legalpacks WHERE case_id=?',(key,)).fetchone()['snapshot'])
        result=calculator.calculate(get_case(c,key),view['review'],values,pack)
        calculation_id=uuid.uuid4().hex
        c.execute('INSERT INTO travel_calculations VALUES (?,?,?,?,?,?,?)',(calculation_id,key,1,dumps(values),dumps(result),dumps(pack),stamp))
        event(c,key,'CALCULATION_SAVED',{'calculation_id':calculation_id,'status':result['status'],'data_origin':'synthetic_demo'})
        snapshot=detail(c,key);draft_id=uuid.uuid4().hex
        c.execute('INSERT INTO travel_drafts VALUES (?,?,?,?,?)',(draft_id,key,1,dumps(snapshot),stamp))
        event(c,key,'DRAFT_CREATED',{'draft_id':draft_id,'case_version':1,'data_origin':'synthetic_demo'})
        return {**detail(c,key),'scenario_reused':False,'prepared_draft_id':draft_id}


@router.get('/legal-packs')
def legal_packs():
    return calculator.load_bundle()


@router.get('/legal-sources/{source_id}')
def legal_source(source_id: str, sha256: str = ''):
    source=calculator.preserved_sources().get((source_id,sha256)) if sha256 else calculator.load_bundle()['sources'].get(source_id)
    if not source: raise HTTPException(404,'출처가 없습니다.')
    try: path=travel_rates.source_path(source)
    except travel_rates.RateTableError as exc: raise HTTPException(409,str(exc)) from exc
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:
        raise HTTPException(409,'보존 원문이 규정팩의 해시와 다릅니다. 출처 무결성을 다시 확인하세요.')
    return FileResponse(path,filename=source['file'],media_type='application/pdf' if path.suffix=='.pdf' else 'application/octet-stream')


@router.post('/cases/{case_id}/calculate')
def calculate_case(case_id: str, body: CalculationInput):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        case=get_case(c,case_id)
        bump(c,case_id,body.version)
        view=detail(c,case_id)
        row=c.execute('SELECT snapshot FROM travel_case_legalpacks WHERE case_id=?',(case_id,)).fetchone()
        pack=json.loads(row['snapshot']) if row else None
        values=body.model_dump(mode='json',exclude={'version'})
        case['unconfirmed_documents']=sum(not d['confirmed_at'] for d in view['documents'])
        result=calculator.calculate(case,view['review'],values,pack)
        key=uuid.uuid4().hex
        c.execute('INSERT INTO travel_calculations VALUES (?,?,?,?,?,?,?)',(
            key,case_id,body.version+1,dumps(values),dumps(result),dumps(pack) if pack else None,now()))
        event(c,case_id,'CALCULATION_SAVED',{'calculation_id':key,'status':result['status'],
            'rulepack_version':result['rulepack_version'],'case_version':body.version+1})
        return detail(c,case_id)


def legal_pack_preview(c,case_id,version):
    case=get_case(c,case_id)
    if case['version']!=version:raise HTTPException(409,'출장이 변경되었습니다. 다시 열어 확인하세요.')
    row=c.execute('SELECT snapshot FROM travel_case_legalpacks WHERE case_id=?',(case_id,)).fetchone()
    latest=calculator.select_pack(case['organization_id'])
    if not row or not latest:raise HTTPException(422,'검증된 공식 계산팩이 연결된 출장에서만 갱신할 수 있습니다.')
    old=json.loads(row['snapshot'])
    if old.get('bundle_sha256')==latest.get('bundle_sha256'):raise HTTPException(422,'이미 최신 확인 기준이 적용되어 있습니다.')
    if old['profile']['id']!=latest['profile']['id']:raise HTTPException(422,'기관 적용 범위가 달라 담당자 재검토가 필요합니다.')
    try:
        travel_rates.checked_table(latest)
        travel_rates.verify_sources(latest,latest['profile']['source_ids'])
    except travel_rates.RateTableError as exc:raise HTTPException(409,str(exc)) from exc
    temporal=travel_validity.assess(latest,case['trip_json']['start_date'],case['trip_json']['end_date'])
    if not temporal['allowed']:raise HTTPException(422,temporal['message'])
    changes=[]
    for key in latest['profile']['source_ids']:
        new=latest['sources'][key];before=old['sources'].get(key,{})
        changes.append(dict(id=key,title=new['title'],before_version=before.get('version'),after_version=new['version'],
            before_verified_on=before.get('verified_on'),after_verified_on=new['verified_on'],
            before_sha256=before.get('sha256'),after_sha256=new['sha256'],url=new['url']))
    digest=hashlib.sha256(dumps({'case_id':case_id,'case_version':version,'old':old,'latest':latest}).encode()).hexdigest()
    return dict(case_id=case_id,version=version,previous_version=old['version'],next_version=latest['version'],
        previous_verified_through=old['verified_through'],next_verified_through=latest['verified_through'],
        source_changes=changes,temporal=temporal,preview_digest=digest,
        next_bundle_sha256=latest['bundle_sha256'],
        rates_unchanged=old.get('domestic_table_sha256')==latest.get('domestic_table_sha256'),
        notice='현재 출장의 계산 기준을 갱신하고 기존 계산은 재계산 대상으로 표시합니다. 증빙과 이전 초안·계산 이력은 그대로 보존합니다.')


@router.get('/cases/{case_id}/legal-pack-preview')
def preview_legal_pack(case_id: str,version: int):
    with db() as c:return legal_pack_preview(c,case_id,version)


@router.post('/cases/{case_id}/legal-pack-update')
def update_legal_pack(case_id: str,body: LegalPackUpdate):
    if not body.confirmed:raise HTTPException(422,'변경 근거와 기존 초안 보존 안내를 확인한 뒤 적용하세요.')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        preview=legal_pack_preview(c,case_id,body.version)
        if preview['preview_digest']!=body.preview_digest:raise HTTPException(409,'규정팩이나 출장 자료가 바뀌었습니다. 변경 내용을 다시 확인하세요.')
        case=get_case(c,case_id);pack=calculator.select_pack(case['organization_id'])
        if pack['bundle_sha256']!=preview['next_bundle_sha256']:raise HTTPException(409,'적용 중 규정팩이 바뀌었습니다. 변경 내용을 다시 확인하세요.')
        selected=[r for r in calculator.searchable_rules(pack) if r['effective_date']<=case['trip_json']['start_date']]
        bump(c,case_id,body.version)
        c.execute('UPDATE travel_case_legalpacks SET snapshot=? WHERE case_id=?',(dumps(pack),case_id))
        c.execute('UPDATE travel_cases SET rule_snapshot=? WHERE id=?',(dumps(selected),case_id))
        event(c,case_id,'LEGAL_PACK_UPDATED',{'from_version':body.version,'to_version':body.version+1,
            'reason':body.reason,'preview':preview})
        return detail(c,case_id)


@router.get("/cases")
def list_cases(q: str='', stage: str='all'):
    if stage!='all' and stage not in travel_workflow.STAGES: raise HTTPException(422,'알 수 없는 업무 상태입니다.')
    if len(q)>200: raise HTTPException(422,'검색어는 200자 이내로 입력하세요.')
    with db() as c:
        result = []
        for r in c.execute("SELECT id,trip_json,profile_snapshot,version,updated_at FROM travel_cases ORDER BY updated_at DESC"):
            row = dict(r)
            row["trip"] = json.loads(row.pop("trip_json"))
            row["organization"] = json.loads(row.pop("profile_snapshot"))["name"]
            if q.strip().casefold() not in (' '.join([row['organization'],row['trip']['destination'],row['trip']['purpose']])).casefold(): continue
            view=detail(c,row['id'])
            row['data_origin']=view['data_origin']
            drafts=case_drafts(c,row['id'],view)
            row.update(travel_workflow.summarize(view,drafts))
            if stage!='all' and row['stage']!=stage: continue
            result.append(row)
        return result


def case_drafts(c,case_id,view):
    return [travel_workflow.draft_row(dict(r),json.loads(r['snapshot']),view) for r in c.execute('SELECT * FROM travel_drafts WHERE case_id=? ORDER BY created_at DESC,id DESC',(case_id,))]


@router.get('/cases/{case_id}/drafts')
def saved_drafts(case_id: str):
    with db() as c:
        view=detail(c,case_id)
        return {'case_id':case_id,'case_version':view['version'],'workflow_revision':view['workflow_revision'],
                'drafts':case_drafts(c,case_id,view)}


def note_context(case):
    snapshot = {key: case[key] for key in ('trip_json', 'profile_snapshot', 'rule_snapshot')}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def stage_notes(c, case):
    context = note_context(case)
    rows = []
    for row in c.execute('SELECT * FROM travel_stage_notes WHERE case_id=? ORDER BY created_at DESC,id', (case['id'],)):
        item = dict(row)
        item['context_changed'] = item['case_version'] != case['version'] or item['context_hash'] != context
        item['verification'] = 'user_unverified'
        task=c.execute('SELECT t.id,t.title,t.status,t.resolution FROM travel_stage_note_tasks l JOIN travel_tasks t ON t.id=l.task_id WHERE l.note_id=? AND t.case_id=?', (item['id'],case['id'])).fetchone()
        item['task'] = dict(task) if task else None
        rows.append(item)
    return {'case_id': case['id'], 'case_version': case['version'], 'notes': rows}


@router.get('/cases/{case_id}/stage-notes')
def get_stage_notes(case_id: str):
    with db() as c:
        return stage_notes(c, get_case(c, case_id))


@router.post('/cases/{case_id}/stage-notes', status_code=201)
def create_stage_note(case_id: str, body: StageNote):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        case = get_case(c, case_id)
        if case['version'] != body.version:
            raise HTTPException(409, '출장·증빙 정보가 변경되었습니다. 업무함에서 다시 열고 기록하세요.')
        c.execute('INSERT INTO travel_stage_notes VALUES (?,?,?,?,?,?,?,?)',
                  (uuid.uuid4().hex, case_id, body.stage, body.title, body.body,
                   case['version'], note_context(case), now()))
        return stage_notes(c, case)


@router.get('/cases/{case_id}/journey')
def case_journey(case_id: str):
    with db() as c:
        view=detail(c,case_id)
        return travel_journey.build(view,case_drafts(c,case_id,view))


def bump_workflow(c,case_id,version,revision):
    case=get_case(c,case_id)
    if case['version']!=version: raise HTTPException(409,'출장 자료가 변경되었습니다. 다시 열어 주세요.')
    c.execute('INSERT OR IGNORE INTO travel_case_workflow VALUES (?,0)',(case_id,))
    changed=c.execute('UPDATE travel_case_workflow SET revision=revision+1 WHERE case_id=? AND revision=?',(case_id,revision))
    if changed.rowcount!=1: raise HTTPException(409,'보완 작업이 변경되었습니다. 다시 열어 주세요.')
    c.execute('UPDATE travel_cases SET updated_at=? WHERE id=?',(now(),case_id))


@router.post('/cases/{case_id}/tasks',status_code=201)
def add_task(case_id: str,body: TaskCreate):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        bump_workflow(c,case_id,body.version,body.workflow_revision)
        key=uuid.uuid4().hex;stamp=now()
        c.execute('INSERT INTO travel_tasks VALUES (?,?,?,?,?,?,?,?)',(key,case_id,body.title,body.note,'open','',stamp,stamp))
        event(c,case_id,'TASK_CREATED',{'task_id':key,'title':body.title,'note':body.note,'workflow_revision':body.workflow_revision+1})
        return detail(c,case_id)


@router.post('/cases/{case_id}/stage-notes/{note_id}/task',status_code=201)
def stage_note_to_task(case_id: str,note_id: str,body: StageNoteTask):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        case=get_case(c,case_id)
        note=c.execute('SELECT * FROM travel_stage_notes WHERE id=? AND case_id=?',(note_id,case_id)).fetchone()
        if not note: raise HTTPException(404,'이 출장의 기록을 찾을 수 없습니다.')
        # 재시도 시 이미 연결한 작업을 반환한다. 보완 버전이나 작업을 중복 생성하지 않는다.
        if c.execute('SELECT 1 FROM travel_stage_note_tasks WHERE note_id=?',(note_id,)).fetchone():
            return detail(c,case_id)
        if not body.export_confirmed:
            raise HTTPException(422,'보완 작업에 입력한 내용의 초안·제출 묶음 포함을 확인하세요.')
        changed=note['case_version']!=case['version'] or note['context_hash']!=note_context(case)
        if changed and not body.context_confirmed:
            raise HTTPException(422,'기록 후 자료가 변경되었습니다. 현재 자료와 대조 후 연결하세요.')
        bump_workflow(c,case_id,body.version,body.workflow_revision)
        key=uuid.uuid4().hex;stamp=now()
        c.execute('INSERT INTO travel_tasks VALUES (?,?,?,?,?,?,?,?)',(key,case_id,body.title,body.note,'open','',stamp,stamp))
        c.execute('INSERT INTO travel_stage_note_tasks VALUES (?,?,?)',(note_id,key,stamp))
        event(c,case_id,'TASK_CREATED',{'task_id':key,'title':body.title,'note':body.note,
              'source_note_id':note_id,'source_stage':note['stage'],'context_rechecked':changed,
              'workflow_revision':body.workflow_revision+1})
        return detail(c,case_id)


@router.patch('/cases/{case_id}/tasks/{task_id}')
def change_task(case_id: str,task_id: str,body: TaskChange):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        get_case(c,case_id)
        task=c.execute('SELECT * FROM travel_tasks WHERE id=? AND case_id=?',(task_id,case_id)).fetchone()
        if not task: raise HTTPException(404,'보완 작업이 없습니다.')
        target='done' if body.action=='done' else 'open'
        if task['status']==target: raise HTTPException(409,'이미 같은 처리 상태입니다.')
        bump_workflow(c,case_id,body.version,body.workflow_revision)
        c.execute('UPDATE travel_tasks SET status=?,resolution=?,updated_at=? WHERE id=?',(target,body.reason,now(),task_id))
        event(c,case_id,'TASK_CHANGED',{'task_id':task_id,'title':task['title'],'from':task['status'],'to':target,'reason':body.reason,'workflow_revision':body.workflow_revision+1})
        return detail(c,case_id)


@router.get("/cases/{case_id}")
def read_case(case_id: str):
    with db() as c:
        return detail(c, case_id)


@router.post("/cases/{case_id}/evidence")
def import_evidence(case_id: str, body: EvidenceImport):
    with db() as c:
        # 쓰기 잠금은 읽기 전에 잡아 버전 확인과 수정 사이 경쟁을 막는다.
        c.execute("BEGIN IMMEDIATE")
        case = get_case(c, case_id)
        bump(c, case_id, body.version)
        trip = case["trip_json"]
        parsed, issues = parse_evidence(body.text, date.fromisoformat(trip["start_date"]), date.fromisoformat(trip["end_date"]), body.source_type)
        inserted, duplicates = 0, 0
        for row in parsed:
            result = c.execute("INSERT OR IGNORE INTO travel_transactions(id,case_id,transaction_date,transaction_time,merchant,amount,category,source_type,fingerprint,cancelled) VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (uuid.uuid4().hex, case_id, row["transaction_date"], row["transaction_time"], row["merchant"], row["amount"], row["category"], body.source_type, row["fingerprint"], row["cancelled"]))
            inserted += result.rowcount
            duplicates += int(result.rowcount == 0)
        # 다른 자료를 추가해도 이전 실패 내역은 사라지지 않는다. 명시적 확인 API로 해소한다.
        c.execute("UPDATE travel_cases SET parse_issues=? WHERE id=?", (dumps(case["parse_issues"] + issues), case_id))
        event(c, case_id, "EVIDENCE_IMPORTED", {"inserted": inserted, "duplicates_skipped": duplicates,
                                               "issues": issues, "source_type": body.source_type})
        return {**detail(c, case_id), "import_result": {"inserted": inserted, "duplicates_skipped": duplicates}}


@router.post('/cases/{case_id}/documents',status_code=201)
def upload_receipt(case_id: str, version: int=Form(...,ge=1), file: UploadFile=File(...)):
    try:
        with db() as c:
            case=get_case(c,case_id)
            if case['version']!=version: raise HTTPException(409,'새 변경이 있습니다. 출장 목록에서 다시 열어 주세요.')
        name=(file.filename or '영수증').replace('\\','/').split('/')[-1]
        name=''.join(ch for ch in name if ch.isprintable())[:180]
        ext=Path(name).suffix.lower()
        raw=file.file.read(travel_files.MAX_BYTES+1)
        try: extracted=travel_files.read_receipt(raw,ext)
        except travel_files.ReceiptError as exc: raise HTTPException(422,str(exc)) from exc
        digest=hashlib.sha256(raw).hexdigest()
        suggestion,warnings=travel_files.suggest_transactions(extracted['text'],date.fromisoformat(case['trip_json']['start_date']),date.fromisoformat(case['trip_json']['end_date']))
        extracted['warnings']+=warnings
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            latest=get_case(c,case_id)
            if latest['version']!=version: raise HTTPException(409,'파일을 읽는 동안 변경이 있습니다. 출장 목록에서 다시 열어 주세요.')
            previous=c.execute('SELECT id FROM travel_documents WHERE case_id=? AND sha256=?',(case_id,digest)).fetchone()
            if previous:
                return {**detail(c,case_id),'upload_result':{'document_id':previous['id'],'duplicate':True}}
            bump(c,case_id,version); key=uuid.uuid4().hex
            c.execute('INSERT INTO travel_documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(key,case_id,name,travel_files.TYPES[ext],digest,raw,dumps(extracted),suggestion,None,None,now(),None))
            event(c,case_id,'DOCUMENT_UPLOADED',{'document_id':key,'filename':name,'sha256':digest,'engine':extracted['engine']})
            return {**detail(c,case_id),'upload_result':{'document_id':key,'duplicate':False}}
    finally:
        file.file.close()


def original_document(c,case_id,document_id):
    get_case(c,case_id)
    row=c.execute('SELECT * FROM travel_documents WHERE id=? AND case_id=?',(document_id,case_id)).fetchone()
    if not row: raise HTTPException(404,'첨부파일이 없습니다.')
    if hashlib.sha256(row['original']).hexdigest()!=row['sha256']: raise HTTPException(409,'보존 원본의 무결성을 확인하세요.')
    return row


@router.get('/cases/{case_id}/documents/{document_id}/original')
def download_receipt(case_id: str,document_id: str):
    from urllib.parse import quote
    with db() as c:
        row=original_document(c,case_id,document_id)
        return Response(row['original'],media_type=row['media_type'],headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(row['filename']), 'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})


@router.get('/cases/{case_id}/documents/{document_id}/preview')
def preview_receipt(case_id: str,document_id: str):
    with db() as c:
        row=original_document(c,case_id,document_id)
        if row['media_type'] not in ('image/png','image/jpeg'): raise HTTPException(422,'이미지 원본만 미리 볼 수 있습니다. PDF는 원본 다운로드를 사용하세요.')
        return Response(row['original'],media_type=row['media_type'],headers={'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})


@router.post('/cases/{case_id}/documents/{document_id}/confirm')
def confirm_receipt(case_id: str,document_id: str,body: DocumentConfirmation):
    if not body.original_checked: raise HTTPException(422,'원본과 거래일·시각·가맹점·금액·취소 여부를 대조하세요.')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        document=original_document(c,case_id,document_id);case=get_case(c,case_id)
        if document['confirmed_at']: raise HTTPException(409,'이미 확인한 파일입니다. 거래의 포함·제외를 검토하세요.')
        trip=case['trip_json']
        parsed,issues=parse_evidence(body.text,date.fromisoformat(trip['start_date']),date.fromisoformat(trip['end_date']),'receipt_text')
        if issues or not parsed: raise HTTPException(422,'거래 형식을 확인하세요: 날짜 시간 가맹점 금액원 승인/취소. 해석하지 못한 줄이 있으면 반영하지 않습니다.')
        bump(c,case_id,body.version); inserted=0
        for row in parsed:
            tx_id=uuid.uuid4().hex
            r=c.execute('INSERT OR IGNORE INTO travel_transactions(id,case_id,transaction_date,transaction_time,merchant,amount,category,source_type,fingerprint,cancelled) VALUES (?,?,?,?,?,?,?,?,?,?)',(tx_id,case_id,row['transaction_date'],row['transaction_time'],row['merchant'],row['amount'],row['category'],'receipt_text',row['fingerprint'],row['cancelled']))
            inserted+=r.rowcount
            saved=c.execute('SELECT id FROM travel_transactions WHERE case_id=? AND fingerprint=?',(case_id,row['fingerprint'])).fetchone()
            c.execute('INSERT OR IGNORE INTO travel_document_transactions VALUES (?,?)',(document_id,saved['id']))
        c.execute('UPDATE travel_documents SET confirmed_text=?,confirmation_reason=?,confirmed_at=? WHERE id=?',(body.text,body.reason,now(),document_id))
        event(c,case_id,'DOCUMENT_CONFIRMED',{'document_id':document_id,'inserted':inserted,'duplicates_linked':len(parsed)-inserted,'reason':body.reason,'confirmed_text':body.text})
        return {**detail(c,case_id),'import_result':{'inserted':inserted,'duplicates_skipped':len(parsed)-inserted}}


@router.post('/cases/{case_id}/documents/{document_id}/dismiss')
def dismiss_receipt(case_id: str,document_id: str,body: IssueResolution):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        document=original_document(c,case_id,document_id)
        if document['confirmed_at']: raise HTTPException(409,'이미 검토한 첨부파일입니다.')
        bump(c,case_id,body.version)
        c.execute('UPDATE travel_documents SET confirmed_text=?,confirmation_reason=?,confirmed_at=? WHERE id=?',('',body.reason,now(),document_id))
        event(c,case_id,'DOCUMENT_DISMISSED',{'document_id':document_id,'reason':body.reason})
        return detail(c,case_id)


@router.post("/cases/{case_id}/resolve-issues")
def resolve_issues(case_id: str, body: IssueResolution):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        case = get_case(c, case_id)
        bump(c, case_id, body.version)
        event(c, case_id, "PARSE_ISSUES_RESOLVED", {"issues": case["parse_issues"], "reason": body.reason})
        c.execute("UPDATE travel_cases SET parse_issues='[]' WHERE id=?", (case_id,))
        return detail(c, case_id)


@router.patch("/cases/{case_id}/transactions/{transaction_id}")
def decide(case_id: str, transaction_id: str, body: Decision):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        get_case(c, case_id)
        old = c.execute("SELECT * FROM travel_transactions WHERE id=? AND case_id=?", (transaction_id, case_id)).fetchone()
        if not old:
            raise HTTPException(404, "거래가 없습니다.")
        if body.decision == "include":
            cancelled = c.execute("SELECT 1 FROM travel_transactions WHERE case_id=? AND merchant=? AND amount=? AND cancelled=1",
                                  (case_id, old["merchant"], old["amount"])).fetchone()
            if old["cancelled"] or cancelled:
                raise HTTPException(422, "취소 연관 거래는 포함할 수 없습니다. 공식 승인내역을 대조하세요.")
        bump(c, case_id, body.version)
        c.execute("UPDATE travel_transactions SET decision=?,reason=?,category=? WHERE id=?",
                  (body.decision, body.reason, body.category, transaction_id))
        event(c, case_id, "TRANSACTION_REVIEWED", {"transaction_id": transaction_id,
            "before": {k: old[k] for k in ("decision", "category", "reason")},
            "after": body.model_dump(exclude={"version"})})
        return detail(c, case_id)


@router.post("/cases/{case_id}/drafts", status_code=201)
def draft(case_id: str, body: Version):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        snapshot = detail(c, case_id)
        if snapshot["version"] != body.version:
            raise HTTPException(409, "새 변경이 있습니다. 다시 조회하세요.")
        # 초안은 보류 상태도 표현하되, 거래가 전혀 없는 문서는 생성하지 않는다.
        current_calculation=snapshot.get('calculation')
        calculated=bool(current_calculation and not current_calculation['stale'] and current_calculation['result']['status']=='calculated_for_review')
        if not snapshot["review"]["transactions"] and not calculated:
            raise HTTPException(422, "거래를 1건 이상 입력하세요.")
        key = uuid.uuid4().hex
        stamp = now()
        c.execute("INSERT INTO travel_drafts VALUES (?,?,?,?,?)", (key, case_id, body.version, dumps(snapshot), stamp))
        event(c, case_id, "DRAFT_CREATED", {"draft_id": key, "case_version": body.version})
        return {"id": key, "case_version": body.version, "created_at": stamp,
                'form_previews':travel_forms.previews(snapshot,key),
                "package_check_url":f"/api/travel/drafts/{key}/package-check", "package_url":f"/api/travel/drafts/{key}/package",
                "json_url": f"/api/travel/drafts/{key}", "csv_url": f"/api/travel/drafts/{key}/csv"}


@router.get('/drafts/{draft_id}/forms/{template_id}',response_class=HTMLResponse)
def preview_draft_form(draft_id: str, template_id: str):
    data=read_draft(draft_id);snapshot=data['snapshot']
    binding=next((b for b in snapshot['profile_snapshot'].get('form_bindings',[]) if b['status']=='ready' and b['template']['id']==template_id),None)
    if not binding: raise HTTPException(404,'이 초안에 저장된 기관 서식이 없습니다.')
    return HTMLResponse(travel_forms.render(binding,snapshot),headers={'X-Content-Type-Options':'nosniff','Cache-Control':'no-store','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"})


@router.get("/drafts/{draft_id}")
def read_draft(draft_id: str):
    with db() as c:
        row = c.execute("SELECT * FROM travel_drafts WHERE id=?", (draft_id,)).fetchone()
        if not row:
            raise HTTPException(404, "초안이 없습니다.")
        snapshot=json.loads(row['snapshot'])
        source_mode='기관 등록자료 · 계산팩 미검증' if snapshot.get('profile_snapshot',{}).get('profile_kind')=='registered' else ('합성 규정 기반' if snapshot.get('demo',True) else '공식 출처 확인 규정 기반')
        origin_notice='[합성 시연자료 · 실제 청구용 아님] ' if snapshot.get('data_origin')=='synthetic_demo' else ''
        return {"schema_version": "travel-draft/1", "draft_id": draft_id, "created_at": row["created_at"],
                "notice": origin_notice+source_mode+" 정산 준비 초안. 지급확정·기존 시스템 전송 아님.",
                "snapshot": snapshot}


def safe_cell(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def prepare_package(draft_id):
    data=read_draft(draft_id)
    snapshot=data['snapshot']
    def document_bytes(document):
        with db() as c:
            row=c.execute('SELECT original FROM travel_documents WHERE id=? AND case_id=?',(document['id'],snapshot['id'])).fetchone()
            if not row: raise travel_package.PackageError('초안에 연결된 원본 파일이 없습니다. 원본을 복구한 뒤 다시 내려받으세요.')
            return row['original']
    sources=calculator.preserved_sources()
    def rule_bytes(rule):
        if rule.get('user_source'):
            source=rule['user_source']
            if source['organization_id']!=snapshot['organization_id']: raise travel_package.PackageError('기관 규정 원문의 소속이 다릅니다.')
            with db() as c:
                row=c.execute('SELECT original,sha256 FROM travel_rule_sources WHERE id=? AND organization_id=?',(source['id'],source['organization_id'])).fetchone()
                if not row or row['sha256']!=source['sha256']: raise travel_package.PackageError('저장 당시 기관 원문을 찾을 수 없습니다.')
                return row['original'],source['extension']
        source=next((s for s in sources.values() if s['url']==rule['source_url'] and s['sha256']==rule['source_sha256']),None)
        if not source: raise travel_package.PackageError('당시 규정 원문을 현재 보존본에서 찾을 수 없습니다. 출처를 재검수하세요.')
        try: path=travel_rates.source_path(source)
        except travel_rates.RateTableError as exc: raise travel_package.PackageError(str(exc)) from exc
        if not path.is_file(): raise travel_package.PackageError('보존한 규정 원문 파일이 없습니다.')
        return path.read_bytes(),'.pdf' if path.suffix=='.pdf' else '.html.txt'
    def template_bytes(template):
        if template['organization_id']!=snapshot['organization_id']: raise travel_package.PackageError('기관 서식의 소속이 다릅니다.')
        with db() as c:
            row=c.execute('SELECT original,sha256 FROM travel_form_templates WHERE id=? AND organization_id=?',(template['id'],snapshot['organization_id'])).fetchone()
            if not row or row['sha256']!=template['sha256']: raise travel_package.PackageError('당시 기관 서식 원본이 없습니다.')
            return row['original']
    try:
        return travel_package.prepare(data,print_draft(draft_id).encode('utf-8'),export_csv(draft_id).body,document_bytes,rule_bytes,template_bytes)
    except travel_package.PackageError as exc: raise HTTPException(409,str(exc)) from exc


@router.get('/drafts/{draft_id}/package-check')
def package_check(draft_id: str):
    manifest,files=prepare_package(draft_id)
    return {**{k:v for k,v in manifest.items() if k not in ('files','rule_sources')},
            'form_previews':[{'name':t['name'],'version':t['version'],'url':f'/api/travel/drafts/{draft_id}/forms/{t["template_id"]}'} for t in manifest.get('form_templates',[])],
            'file_count':len(files),'total_uncompressed_bytes':sum(len(raw) for raw in files.values()),
            'files':manifest['files'], 'rule_sources':manifest['rule_sources'],
            'package_url':f'/api/travel/drafts/{draft_id}/package'}


@router.get('/drafts/{draft_id}/package')
def export_package(draft_id: str):
    manifest,files=prepare_package(draft_id)
    return Response(travel_package.archive(manifest,files),media_type='application/zip',
                    headers={'Content-Disposition':f'attachment; filename="travel-package-{draft_id[:8]}.zip"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@router.get("/drafts/{draft_id}/csv")
def export_csv(draft_id: str):
    data = read_draft(draft_id)
    snap = data["snapshot"]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    if snap.get('data_origin')=='synthetic_demo':writer.writerow(['합성 시연자료 · 실제 청구·지급 증빙으로 사용할 수 없습니다'])
    writer.writerow([("기관 등록자료 · 계산팩 미검증 · " if snap.get('profile_snapshot',{}).get('profile_kind')=='registered' else ("모의 " if snap.get('demo',True) else "공식 출처 확인 규정 · "))+"출장정산 준비 초안 · 지급확정 아님"])
    writer.writerow(["기관", safe_cell(snap["profile_snapshot"]["name"])])
    writer.writerow(["출장지", safe_cell(snap["trip_json"]["destination"]), "시작", snap["trip_json"]["start_date"], "종료", snap["trip_json"]["end_date"]])
    writer.writerow(["거래일", "시간", "가맹점", "금액", "분류", "후보포함", "확인상태", "사유", "검토사항"])
    for row in snap["review"]["transactions"]:
        writer.writerow([row["transaction_date"], row["transaction_time"], safe_cell(row["merchant"]), row["amount"],
                         LABELS[row["category"]], "예" if row["included"] else "아니오", "거래확인·진위미검증",
                         safe_cell(row["reason"]), "; ".join(row["flags"])])
    writer.writerow(["포함한 거래 후보 합계", snap["review"]["candidate_total"], "실제 지급액", "미산정"])
    calc=snap.get('calculation')
    if calc:
        writer.writerow(['규정 기준 계산','재계산 필요' if calc['stale'] else calc['result']['status']])
        if not calc['stale']:
            temporal=calc['result'].get('temporal')
            if temporal:
                temporal_label='예정 출장 사전산정' if temporal['is_estimate'] else '확인 기간 내 산정' if temporal['allowed'] else '적용 기준 확인 필요 · 계산 보류'
                writer.writerow(['기준 확인일',temporal['reviewed_through'],'계산 구분',temporal_label])
                if temporal['is_estimate']:writer.writerow(['사전산정 주의',safe_cell(temporal['message'])])
            for item in calc['result']['lines']:
                writer.writerow([item['label'],item['amount'],safe_cell(item['formula'])])
                for ref in item['basis']:
                    writer.writerow(['산정 근거',ref['document'],ref['article'],ref['source_version'],ref['effective_date'],ref['url'],ref['source_sha256']])
            for blocked in calc['result']['blockers']:
                writer.writerow(['계산 보류',safe_cell(blocked['message'])])
            writer.writerow(['규정 기준 산정액 · 승인 전',calc['result']['estimated_total'] if calc['result']['estimated_total'] is not None else '보류'])
    writer.writerow(["다음 할 일"])
    for action in snap["review"]["next_actions"]:
        writer.writerow([safe_cell(action)])
    writer.writerow(["근거자료 · 조항별 출처 상태 확인"])
    for r in snap["rule_snapshot"]:
        writer.writerow([safe_cell(r["title"]), safe_cell(r["article"]), safe_cell(r["version"]), r["effective_date"], r["status"], safe_cell(r["text"])])
    return Response(content=("\ufeff" + stream.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="travel-draft-{draft_id[:8]}.csv"'})


@router.get("/drafts/{draft_id}/print", response_class=HTMLResponse)
def print_draft(draft_id: str):
    data = read_draft(draft_id)
    snap = data["snapshot"]
    trip, review, profile = snap["trip_json"], snap["review"], snap["profile_snapshot"]
    esc = lambda value: html.escape(str(value))
    rows = "".join(
        f'<tr><td>{esc(r["transaction_date"])}</td><td>{esc(r["merchant"])}</td>'
        f'<td>{LABELS[r["category"]]}</td><td class="number">{r["amount"]:,}</td>'
        f'<td>{"포함" if r["included"] else "제외" if r["decision"] == "exclude" else "보류"}</td>'
        f'<td>{esc(r["reason"])}<small>{esc(" / ".join(r["flags"]))}</small></td></tr>'
        for r in review["transactions"])
    actions = "".join(f'<li>{esc(a)}</li>' for a in review["next_actions"])
    sources = "".join(f'<li><b>{esc(r["title"])}</b> · {esc(r["article"])} · 버전 {esc(r["version"])}'
                      f'<small>시행 {esc(r["effective_date"])} / 종료(미포함) {esc(r["expiry_date"] or "없음")} / {esc(r["status"])}</small>'
                      f'<p>{esc(r["text"])}</p></li>' for r in snap["rule_snapshot"])
    for rule in snap['rule_snapshot']:
        user_review=rule.get('user_review')
        if user_review:
            source=user_review['source']
            outcome='원문 대조 완료 기록' if user_review['outcome']=='checked' else '보완 필요'
            sources+=f'<li><b>사용자 등록 원문 · 공식 인증 아님</b> {esc(source["title"])} / {esc(source["issuer"])}<small>출처 {esc(source["source_url"] or "주소 미등록")}<br>SHA-256 {esc(source["sha256"])}<br>위치 {esc(user_review["location"])} / {outcome} / 기록자(사용자 입력) {esc(user_review["reviewer"])} / 이력 버전 {user_review["revision"]}</small><p>{esc(user_review["note"])}</p></li>'
    calculation_section=calculation_print(snap.get('calculation'))
    attachments=''
    if snap.get('documents'):
        attachments='<h2>첨부 원본·확인 기록</h2><ul>'+''.join(
            f'<li>{esc(d["filename"])} / {"거래 반영" if d["confirmed_text"] else "제외" if d["confirmed_at"] else "원본 대조 필요"}'
            f'<small>원본 SHA-256: {esc(d["sha256"])}<br>확인 사유: {esc(d["confirmation_reason"] or "미확인")}</small></li>'
            for d in snap['documents'])+'</ul>'
    tasks=''
    if snap.get('tasks'):
        tasks='<h2>보완 작업·메모 사본</h2><ul>'+''.join(
            f'<li>{esc(t["title"])} / {"미완료" if t["status"]=="open" else "완료 기록"}'
            f'<small>{esc(t["note"])}<br>처리 사유: {esc(t["resolution"] or "미처리")}</small></li>' for t in snap['tasks'])+'</ul>'
    source_mode='기관 등록자료 · 계산팩 미검증' if snap.get('profile_snapshot',{}).get('profile_kind')=='registered' else ('합성 규정 기반 시연' if snap.get('demo',True) else '공식 출처 확인 규정 · 최종 승인 전')
    if snap.get('data_origin')=='synthetic_demo':source_mode='합성 시연자료 · 실제 청구용 아님 / '+source_mode
    return '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + \
        '<title>출장정산 준비 초안</title><style>body{max-width:1000px;margin:40px auto;padding:0 24px;color:#20374b;font:14px/1.8 system-ui,sans-serif}h1{font-size:27px}h2{font-size:18px;margin-top:30px}table{width:100%;border-collapse:collapse;font-size:12px}th,td{border:1px solid #ccd8e2;padding:10px;text-align:left;vertical-align:top}th{background:#edf3fa}.number{text-align:right;white-space:nowrap}.notice{background:#fff2da;padding:15px}small{display:block;color:#66788b}li{margin-bottom:10px}p{margin:8px 0}a{color:#2466cf}@media print{body{margin:0;max-width:none;font-size:10pt}a{display:none}thead{display:table-header-group}tr,li{break-inside:avoid}@page{size:A4;margin:16mm}}</style>' + \
        f'<body><small>서무비서 / {source_mode} / 출장 버전 {snap["version"]}</small><h1>출장정산 준비 초안</h1>' + \
        '<div class="notice"><b>검토용 초안 · 지급확정 아님</b><br>모든 거래의 증빙 진위는 미검증입니다. 규정 계산의 지원범위·입력조건·보류 사유와 담당자 승인을 확인하세요.</div>' + \
        f'<h2>출장 개요</h2><p>{esc(profile["name"])} / {esc(profile["personnel_type"])} / {esc(profile["work_pattern"])}</p>' + \
        f'<p>{esc(trip["destination"])} · {esc(trip["purpose"])} / {esc(trip["start_date"])} ~ {esc(trip["end_date"])}</p>' + \
        f'<p>이동: {esc(trip["transport"])} / 숙박: {"있음" if trip["overnight"] else "없음"} / 식사 제공: {"있음" if trip["meals_provided"] else "없음"}</p>' + \
        '<h2>거래·증빙 목록</h2><table><thead><tr><th>거래일</th><th>가맹점</th><th>분류</th><th>금액(원)</th><th>후보 처리</th><th>사유·검토사항</th></tr></thead>' + \
        f'<tbody>{rows}</tbody></table><p><b>포함한 거래 후보 합계: {review["candidate_total"]:,}원</b> / 실제 지급액: 미산정</p>' + \
        calculation_section + attachments + tasks + f'<h2>다음 할 일·미확인 사항</h2><ul>{actions}</ul><h2>근거자료 사본</h2><ul>{sources}</ul>' + \
        f'<small>초안 ID {esc(draft_id)} / 생성 {esc(data["created_at"])} / 원문 파일·공식 증빙은 별도 첨부</small>' + \
        '<p>브라우저 인쇄 메뉴에서 출력하거나 PDF로 저장할 수 있습니다.</p></body></html>'


def calculation_print(calc):
    if not calc: return '<h2>규정 기준 계산</h2><p>계산하지 않았습니다.</p>'
    if calc['stale']: return '<h2>규정 기준 계산</h2><p>거래·검토 상태 변경으로 재계산이 필요합니다. 이전 산정액은 사용하지 않습니다.</p>'
    result=calc['result']; esc=lambda s: html.escape(str(s))
    out=['<h2>규정 기준 계산 · 승인 전</h2>']
    if result.get('temporal',{}).get('is_estimate'):
        out.append(f'<p><b>예정 출장 사전산정</b><br>{esc(result["notice"])}</p>')
    training=calc['inputs'].get('training')
    if training:
        out.append(f'<p>교육기관 안내문·청구서: {esc(training["notice_reference"])}<br>입교 {esc(training["entry_date"])} / 수료 {esc(training["completion_date"])} / {"합숙·기숙사" if training["residential"] else "비합숙"}<br>미발생·미청구 항목: {esc(", ".join(training["zero_items"]) or "없음")}</p>')
    for item in result['lines']:
        out.append(f'<h3>{esc(item["label"])} {item["amount"]:,}원</h3><p>{esc(item["formula"])}</p><ul>')
        for ref in item['basis']:
            out.append(f'<li>{esc(ref["document"])} {esc(ref["article"])} / {esc(ref["source_version"])} / 시행 {esc(ref["effective_date"])}'
                       f'<small>{esc(ref["summary"])}<br>원문: {esc(ref["url"])}<br>SHA-256: {esc(ref["source_sha256"])}</small></li>')
        out.append('</ul>')
    for item in result['blockers']:
        out.append(f'<p>보류: {esc(item["message"])}</p>')
        for ref in item['basis']: out.append(f'<small>{esc(ref["document"])} {esc(ref["article"])} / {esc(ref["url"])}</small>')
    out.append('<b>규정 기준 산정액: '+(f'{result["estimated_total"]:,}원' if result['estimated_total'] is not None else '보류')+'</b>')
    return ''.join(out)
