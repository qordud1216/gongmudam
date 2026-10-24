"""실행 코드 없는 텍스트 서식을 출장 사본으로 채운다. 지급 확정은 하지 않는다."""
import hashlib
import html
import re
from datetime import date
from pydantic import Field, model_validator
from .travel_models import StrictModel

MAX_BYTES=128*1024
TOKENS=('기관명','직군','근무형태','출장지','출장목적','시작일','종료일','출장기간','교통수단','거래후보합계','규정산정액','최종지급액')
PATTERN=re.compile(r'\{\{([^{}]+)\}\}')


class TemplateMetadata(StrictModel):
    name: str=Field(min_length=1,max_length=150)
    version: str=Field(min_length=1,max_length=40)
    effective_date: date
    expiry_date: date|None=None

    @model_validator(mode='after')
    def dates(self):
        if self.expiry_date and self.expiry_date<=self.effective_date: raise ValueError('종료일(미포함)은 시행일 뒤여야 합니다.')
        return self


def read_template(raw, filename):
    filename=filename.replace('\\','/').split('/')[-1]
    if not filename.lower().endswith('.txt') or len(filename)>180 or any(ord(c)<32 for c in filename): raise ValueError('서식은 파일명 180자 이하 UTF-8 TXT로 등록하세요.')
    if not raw or len(raw)>MAX_BYTES: raise ValueError('서식은 1바이트~128KB로 등록하세요.')
    try: text=raw.decode('utf-8-sig')
    except UnicodeError as exc: raise ValueError('UTF-8 텍스트 서식만 지원합니다.') from exc
    if not text.strip() or '\x00' in text: raise ValueError('정상적인 텍스트 서식을 등록하세요.')
    unknown=set(PATTERN.findall(text))-set(TOKENS)
    if unknown: raise ValueError('지원하지 않는 채움 항목: '+', '.join(sorted(unknown)))
    if '{{' in PATTERN.sub('',text) or '}}' in PATTERN.sub('',text): raise ValueError('채움 항목은 {{기관명}}처럼 중괄호 두 쌍으로 입력하세요.')
    if not PATTERN.search(text): raise ValueError('채움 항목을 하나 이상 넣으세요. 예: {{기관명}}')
    return filename,text


def metadata(row):
    return {key:row[key] for key in ('id','organization_id','name','version','effective_date','expiry_date','filename','sha256','created_at')}


def bindings(c, org, start, end):
    result=[]
    for name in org['settings']['required_forms']:
        rows=c.execute('SELECT * FROM travel_form_templates WHERE organization_id=? AND name=? AND effective_date<=? AND (expiry_date IS NULL OR expiry_date>?) ORDER BY effective_date,version,id',(org['id'],name,end,start)).fetchall()
        candidates=[metadata(r) for r in rows]
        status='missing' if not rows else 'overlap' if len(rows)>1 else 'partial' if rows[0]['effective_date']>start or (rows[0]['expiry_date'] and rows[0]['expiry_date']<=end) else 'ready'
        binding={'name':name,'status':status,'candidates':candidates}
        if status=='ready':
            row=rows[0]
            if hashlib.sha256(row['original']).hexdigest()!=row['sha256']: raise ValueError('등록한 서식 원본의 해시가 다릅니다. 복구한 뒤 출장을 저장하세요.')
            filename,text=read_template(row['original'],row['filename'])
            binding.update(template=metadata(row),template_text=text)
        result.append(binding)
    return result


def fill(binding, snapshot):
    trip=snapshot['trip_json'];profile=snapshot['profile_snapshot'];calc=snapshot.get('calculation')
    amount='미산정 · 계산 또는 조건 확인 필요'
    if calc:
        if calc['stale']: amount='재계산 필요 · 이전 산정액 사용 금지'
        elif calc['result']['status']=='calculated_for_review' and calc['result']['estimated_total'] is not None: amount=f"{calc['result']['estimated_total']:,}원 · 검토용"
        else: amount='보류 · 계산 조건·근거 확인 필요'
    values=dict(zip(TOKENS,[profile['name'],profile['personnel_type'],profile['work_pattern'],trip['destination'],trip['purpose'],trip['start_date'],trip['end_date'],trip['start_date']+' ~ '+trip['end_date'],trip['transport'],f"{snapshot['review']['candidate_total']:,}원 · 거래 후보",amount,'미확정 · 담당자 승인 필요']))
    # One substitution pass: user input that resembles a token is never expanded again.
    return PATTERN.sub(lambda m:values[m.group(1)],binding['template_text'])


def render(binding, snapshot):
    template=binding['template'];esc=lambda s:html.escape(str(s))
    return '<!doctype html><html lang="ko"><meta charset="utf-8"><title>기관 서식 검토 초안</title><style>body{max-width:900px;margin:35px auto;padding:20px;font:15px/1.8 system-ui;color:#20374b}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;border:1px solid #ccd8e2;padding:24px}.notice{background:#fff0da;padding:16px}small{overflow-wrap:anywhere}@media print{body{margin:0;padding:0}@page{size:A4;margin:16mm}}</style><h1>'+esc(binding['name'])+' · 검토 초안</h1><p class="notice">자동 채움 초안 · 지급확정·기관 승인 아님. 기관 서식 원본과 대조 후 기존 출장·회계시스템에서 최종 작성하세요. 원본의 편집·인쇄 양식을 재현하는 기능은 아닙니다.</p><pre>'+esc(fill(binding,snapshot))+'</pre><small>기관: '+esc(snapshot['profile_snapshot']['name'])+' / 출장 버전 '+str(snapshot['version'])+' / 서식 버전 '+esc(template['version'])+'<br>원본 파일: '+esc(template['filename'])+' / SHA-256 '+esc(template['sha256'])+'</small></html>'


def previews(snapshot,draft_id):
    return [{'name':b['name'],'version':b['template']['version'],'url':f"/api/travel/drafts/{draft_id}/forms/{b['template']['id']}"} for b in snapshot['profile_snapshot'].get('form_bindings',[]) if b['status']=='ready']
