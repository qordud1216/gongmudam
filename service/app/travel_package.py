"""저장된 초안 기준의 재현 가능한 제출 준비 ZIP. 최종 제출/승인은 수행하지 않는다."""
import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime
from . import travel_forms

MAX_PACKAGE_BYTES=50*1024*1024
EXTENSIONS={'application/pdf':'.pdf','image/png':'.png','image/jpeg':'.jpg'}


class PackageError(ValueError): pass


def encoded(value):
    return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')


def make_csv(rows):
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    for row in rows:
        writer.writerow(["'"+str(v) if str(v).lstrip().startswith(('=','+','-','@')) else v for v in row])
    return ('\ufeff'+stream.getvalue()).encode('utf-8')


def checklist(snapshot):
    items=[]; calc=snapshot.get('calculation')
    fresh=bool(calc and not calc['stale'] and calc['result']['status']=='calculated_for_review')
    if not calc: items.append(dict(code='NO_CALCULATION',level='required',message='규정 기준 계산을 실행하세요.'))
    elif calc['stale']: items.append(dict(code='STALE_CALCULATION',level='required',message='초안 저장 당시 계산이 오래된 상태입니다. 현재 건을 재계산하고 새 초안을 만드세요.'))
    elif not fresh:
        items += [dict(code='CALC_'+b['code'],level='required',message=b['message']) for b in calc['result']['blockers']]
    if fresh and calc['result'].get('temporal',{}).get('is_estimate'):
        items.append(dict(code='FUTURE_ESTIMATE',level='required',message='예정 출장의 사전산정입니다. 여행 종료 후 실제 내역·최신 규정으로 재계산하고 새 초안을 만드세요.'))
    for finding in snapshot['review']['findings']:
        if finding['code'] in ('PARSE','PENDING','NO_RULE','RULE_CHANGE','RULE_CONFLICT','DOCUMENT_UNCONFIRMED','EMPTY','LODGING'):
            if finding['code']=='EMPTY' and fresh: continue
            if finding['code']=='LODGING' and fresh and calc['inputs'].get('lodging_not_claimed'): continue
            items.append(dict(code=finding['code'],level='required',message=finding['message']))
    for tx in snapshot['review']['transactions']:
        if not tx['included']: continue
        if tx['flags']: items.append(dict(code='TRANSACTION_FLAGS',level='required',message=f"{tx['transaction_date']} {tx['merchant']}: {' / '.join(tx['flags'])}",transaction_id=tx['id']))
        if not tx.get('document_ids'): items.append(dict(code='ORIGINAL_NOT_LINKED',level='required',message=f"{tx['transaction_date']} {tx['merchant']} {tx['amount']:,}원: 연결한 원본이 없습니다. 인정 증빙을 확인·첨부하세요.",transaction_id=tx['id']))
    if fresh and calc['inputs'].get('training'):
        items.append(dict(code='TRAINING_BILL_REVIEW',level='handoff',message='교육기관 안내문·청구서·직접 지급 내역과 수기 입력한 숙식비를 담당자가 대조해야 합니다.'))
    items.append(dict(code='OFFICIAL_APPROVAL',level='handoff',message='증빙 진위·기관 승인·최종 지급액은 담당자가 확인하고 기존 출장·회계시스템에서 제출하세요.'))
    for form in snapshot.get('profile_snapshot',{}).get('settings',{}).get('required_forms',[]):
        items.append(dict(code='ORGANIZATION_FORM',level='handoff',message='기관 준비서식 대조: '+form+' · 첨부·승인 여부는 담당자가 확인하세요.'))
    if snapshot.get('profile_snapshot',{}).get('profile_kind')=='registered':
        for rule in snapshot['rule_snapshot']:
            review=rule.get('user_review')
            if not review or review['outcome']=='needs_revision':
                items.append(dict(code='RULE_SOURCE_REVIEW',level='required',message=rule['title']+' '+rule['article']+' · 원문 연결·대조 또는 보완이 필요합니다.'))
    for binding in snapshot.get('profile_snapshot',{}).get('form_bindings',[]):
        if binding['status']!='ready':
            labels={'missing':'파일 미등록','overlap':'버전 중복','partial':'기간 일부 적용'}
            items.append(dict(code='FORM_TEMPLATE_REVIEW',level='required',message=binding['name']+' · '+labels[binding['status']]+' · 자동 채움 초안을 만들지 않았습니다.'))
    if snapshot.get('data_origin')=='synthetic_demo':
        items.append(dict(code='SYNTHETIC_DATA',level='handoff',message='합성 시연자료입니다. 실제 청구·지급 증빙으로 사용하지 마세요.'))
    for task in snapshot.get('tasks',[]):
        if task['status']=='open': items.append(dict(code='OPEN_MANUAL_TASK',level='required',message='미완료 보완 작업: '+task['title'],task_id=task['id']))
    return items


def select_documents(snapshot):
    selected=[];omitted=[]
    for document in snapshot.get('documents',[]):
        linked=[t for t in snapshot['review']['transactions'] if document['id'] in t.get('document_ids',[])]
        if not document['confirmed_at']:
            selected.append((document,'검토대기'))
        elif document['confirmed_text'] and any(t['included'] for t in linked):
            selected.append((document,'영수증'))
        elif document['confirmed_text'] and any(t['decision']=='pending' for t in linked):
            selected.append((document,'검토대기'))
        else:
            omitted.append(dict(id=document['id'],filename=document['filename'],sha256=document['sha256'],reason='파일 제외 또는 연결 거래가 모두 제외됨'))
    return selected,omitted


def prepare(data,html_bytes,csv_bytes,load_document,load_rule,load_template=None):
    snap=data['snapshot'];items=checklist(snap);files={};total=0
    def add(path,raw):
        nonlocal total
        if path in files: raise PackageError('묶음 안의 파일 경로가 중복됩니다.')
        total+=len(raw)
        if total>MAX_PACKAGE_BYTES: raise PackageError('묶음이 50MB를 넘습니다. 영수증을 분리하거나 담당자에게 별도로 전달하세요.')
        files[path]=raw
    add('01_정산서_초안.html',html_bytes)
    add('02_정산_준비표.csv',csv_bytes)
    add('03_정산_사본.json',encoded(data))
    form_index=[]
    for binding in snap['profile_snapshot'].get('form_bindings',[]):
        if binding['status']!='ready': continue
        template=binding['template']
        if load_template is None: raise PackageError('기관 서식 원본을 불러올 수 없습니다.')
        raw=load_template(template)
        if hashlib.sha256(raw).hexdigest()!=template['sha256']: raise PackageError('기관 서식 원본이 저장 당시 해시와 다릅니다.')
        try: _,text=travel_forms.read_template(raw,template['filename'])
        except ValueError as exc: raise PackageError(str(exc)) from exc
        if text!=binding['template_text']: raise PackageError('기관 서식 사본과 원본 내용이 다릅니다.')
        n=len(form_index)+1;original_path=f'기관서식/{n:03d}_원본.txt';preview_path=f'기관서식/{n:03d}_검토초안.html'
        add(original_path,raw);add(preview_path,travel_forms.render(binding,snap).encode('utf-8'))
        form_index.append(dict(template_id=template['id'],name=binding['name'],version=template['version'],sha256=template['sha256'],original_path=original_path,preview_path=preview_path,notice='텍스트 자동 채움 초안 · 지급확정·기관 승인 아님'))
    rows=io.StringIO(newline='');w=csv.writer(rows);w.writerow(['구분','확인 항목','처리 상태'])
    for item in items:
        value=item['message']
        if value.lstrip().startswith(('=','+','-','@')):value="'"+value
        w.writerow(['추가 확인' if item['level']=='required' else '담당자 검토',value,'미완료'])
    add('04_누락_검토목록.csv',('\ufeff'+rows.getvalue()).encode('utf-8'))
    selected,omitted=select_documents(snap);document_index=[]
    for n,(document,folder) in enumerate(selected,1):
        raw=load_document(document)
        if hashlib.sha256(raw).hexdigest()!=document['sha256']: raise PackageError('영수증 원본이 저장 당시 해시와 다릅니다. 원본 무결성을 확인하세요.')
        ext=EXTENSIONS.get(document['media_type'])
        if not ext: raise PackageError('지원하지 않는 원본 형식이 있습니다.')
        path=f'{folder}/{n:03d}{ext}'
        add(path,raw)
        document_index.append(dict(document_id=document['id'],original_filename=document['filename'],archive_path=path,sha256=document['sha256']))
    sources={}
    for rule in snap['rule_snapshot']:
        if rule.get('source_sha256') and rule.get('source_url'):
            sources[(rule['source_url'],rule['source_sha256'])]=rule
        review=rule.get('user_review')
        if review:
            source=review['source']
            sources[(source['original_url'],source['sha256'])]={'title':rule['title'],'source_url':source['original_url'],'source_sha256':source['sha256'],'user_source':source}
    calc=snap.get('calculation')
    if calc:
        for item in calc['result'].get('lines',[])+calc['result'].get('blockers',[]):
            for ref in item.get('basis',[]):
                sources[(ref['url'],ref['source_sha256'])]={'title':ref['document'],'source_url':ref['url'],'source_sha256':ref['source_sha256']}
    rule_index=[]
    for n,(_,rule) in enumerate(sorted(sources.items()),1):
        raw,extension=load_rule(rule)
        if hashlib.sha256(raw).hexdigest()!=rule['source_sha256']: raise PackageError('근거 규정 원문이 저장 당시 해시와 다릅니다. 출처를 재검수하세요.')
        path=f'근거원문/{n:03d}{extension}'
        add(path,raw)
        record=dict(title=rule['title'],url=rule['source_url'],archive_path=path,sha256=rule['source_sha256'])
        if rule.get('user_source'): record.update(origin='user_registered',notice='사용자 등록 원문 · 공식 인증 아님',declared_url=rule['user_source']['source_url'])
        rule_index.append(record)
    document_rows=[['원래 파일명','묶음 안 위치','원본 상태','원본 SHA-256','확인 사유']]
    indexed={d['document_id']:d for d in document_index}
    for document in snap.get('documents',[]):
        included=indexed.get(document['id'])
        document_rows.append([document['filename'],included['archive_path'] if included else '원본 제외',
                              '원본 대조 필요' if not document['confirmed_at'] else '거래 반영' if document['confirmed_text'] else '제외',
                              document['sha256'],document.get('confirmation_reason') or '미확인'])
    add('05_증빙원본_목록.csv',make_csv(document_rows))
    if any(r.get('origin')=='user_registered' for r in rule_index):
        add('06_근거원문_목록.csv',make_csv([['규정명','묶음 안 위치','등록 출처·주소 미등록 시 보존 위치','원문 SHA-256','자료 구분']]+[[r['title'],r['archive_path'],r.get('declared_url') or r['url'],r['sha256'],r.get('notice','공식 출처 확인 원문')] for r in rule_index]))
    else:
        add('06_근거원문_목록.csv',make_csv([['규정명','묶음 안 위치','공식 출처','원문 SHA-256']]+[[r['title'],r['archive_path'],r['url'],r['sha256']] for r in rule_index]))
    status='추가 확인 필요' if any(i['level']=='required' for i in items) else '담당자 검토 준비'
    readme=f'''출장정산 제출 준비 묶음 · {status}

초안 ID: {data['draft_id']}
출장 버전: {snap['version']}
초안 저장: {data['created_at']}

이 묶음은 저장한 초안의 사본입니다. 이후 거래 변경은 반영하지 않습니다.
지급 확정·기관 승인·기존 시스템 제출은 수행하지 않았습니다.

01_정산서_초안.html: 브라우저에서 열어 확인·인쇄하세요.
02_정산_준비표.csv: 거래·계산식·근거를 확인하세요.
03_정산_사본.json: 당시 입력·계산·원본 연결·이력입니다.
04_누락_검토목록.csv: 추가 확인과 담당자 검토 사항입니다.
05_증빙원본_목록.csv: 원래 파일명·묶음 안 위치·확인 사유입니다.
06_근거원문_목록.csv: 규정명·묶음 안 위치·공식 출처입니다.
영수증/: 포함 거래에 연결한 원본입니다. 진위 인증을 의미하지 않습니다.
검토대기/: 확인 전 파일 또는 보류 거래의 원본입니다.
근거원문/: 당시 출처 해시와 대조한 규정 원문입니다.
manifest.json: 파일별 SHA-256과 원래 파일명·출처·제외 원본 목록입니다.

제외된 원본 {len(omitted)}건은 묶음에 넣지 않았습니다. 제외 이력은 사본과 목록에 남아 있습니다.
같은 거래에 여러 원본이 연결되어도 거래 금액을 중복 합산하지 않습니다.
manifest.json 자체의 해시는 자기참조를 피하기 위해 파일 목록에 포함하지 않습니다.
'''
    if snap.get('data_origin')=='synthetic_demo':readme='[합성 시연자료 · 실제 청구·지급용 아님]\n'+readme
    if form_index: readme+='\n기관서식/: 저장 당시 텍스트 서식 원본과 자동 채움 검토 초안입니다. 실제 지급·기관 승인을 의미하지 않습니다.\n'
    add('00_먼저_읽어주세요.txt',readme.encode('utf-8-sig'))
    manifest=dict(schema_version='travel-package/1',draft_id=data['draft_id'],case_id=snap['id'],case_version=snap['version'],snapshot_created_at=data['created_at'],status=status,payable_amount=None,
                  notice='담당자 검토·제출 전 준비자료입니다. 지급확정·승인·시스템 전송을 수행하지 않았습니다.',
                  checklist=items,documents=document_index,omitted_documents=omitted,rule_sources=rule_index,
                  files=[dict(path=p,size=len(raw),sha256=hashlib.sha256(raw).hexdigest()) for p,raw in files.items()],manifest_self_hash_included=False)
    if form_index: manifest['form_templates']=form_index
    if snap.get('data_origin')=='synthetic_demo':
        manifest['data_origin']='synthetic_demo';manifest['notice']='합성 시연자료 · 실제 청구용 아님. '+manifest['notice']
    add('manifest.json',encoded(manifest))
    return manifest,files


def archive(manifest,files):
    created=datetime.fromisoformat(manifest['snapshot_created_at'])
    stamp=(max(1980,min(2107,created.year)),created.month,created.day,created.hour,created.minute,created.second)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path,raw in files.items():
            entry=zipfile.ZipInfo(path,stamp);entry.compress_type=zipfile.ZIP_DEFLATED
            entry.external_attr=0o100644<<16
            bundle.writestr(entry,raw)
    return out.getvalue()
