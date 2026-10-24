"""Build reviewed annex/decree excerpts from saved official downloads, without replacing earlier packs."""
import hashlib
import json
import re
import shutil
from pathlib import Path
from pypdf import PdfReader
from tools.prepare_official_pack import Tree, BASE

STAGING = BASE.parents[2] / 'work/sources-v40'
DECREE = '지방자치단체를 당사자로 하는 계약에 관한 법률 시행령'


def build(staging=None):
    if staging is None:
        staging=BASE if (BASE/'extended_downloads.json').exists() else STAGING
    specs = [
        ('travel_annex1','공무원 여비 규정','별표 1 여비 지급 구분표','국가공무원 · 지방공무원 적용은 해당 여비 조례 확인'),
        ('travel_annex2','공무원 여비 규정','별표 2 국내 여비 지급표','국가공무원 · 지방공무원 적용은 해당 여비 조례 확인'),
        ('travel_annex4','공무원 여비 규정','별표 4 국외 여비 지급표','국가공무원 · 지방공무원 적용은 해당 여비 조례 확인'),
        ('leave_annex1','지방공무원 복무규정','별표 1 경조사 휴가일수표','지방공무원 · 별표 외 사유는 기관 조례 확인'),
        ('national_leave_annex2','국가공무원 복무규정','별표 2 경조사별 휴가 일수표','국가공무원'),
    ]
    used_keys=[key for key, *_ in specs]+[f'goods_decree_{n}' for n in (30,64,65,67,68)]+['national_leave_20']
    if (staging/'extended_downloads.json').exists():
        download_rows=json.loads((staging/'extended_downloads.json').read_text(encoding='utf-8'))
    else:
        download_rows=[r for f in ('downloads.json','annex_downloads.json')
                       for r in json.loads((staging/f).read_text(encoding='utf-8'))]
    downloads={r['key']:r for r in download_rows}
    path=BASE/'manifest.json';records=[r for r in json.loads(path.read_text(encoding='utf-8')) if r.get('collection')!='v40']
    rows=[]
    def save(key,title,label,institution,text,effective,publication,pages=None):
        source=downloads[key];raw=staging/source['file']
        assert hashlib.sha256(raw.read_bytes()).hexdigest()==source['raw_sha256']
        archived=BASE/raw.name
        if raw.resolve()!=archived.resolve():shutil.copy2(raw,archived)
        # The folder TXT parser trims line indentation; normalize the saved excerpt identically.
        text='\n'.join(line.strip() for line in text.splitlines() if line.strip())+'\n'
        target=BASE/'excerpts'/(title+'_'+key+'.txt');target.write_text(text,encoding='utf-8')
        row=dict(title=title,article=label,effective_date=effective,publication=publication,
            issuer='인사혁신처' if title in ('공무원 여비 규정','국가공무원 복무규정') else '행정안전부',
            institution=institution,kind='법령·규정',source_url=source.get('source_url',source['url']),
            download_url=source['url'],retrieved_at=source['retrieved_at'],raw_file=raw.name,
            raw_sha256=source['raw_sha256'],filename=target.name,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            scope='공식 현행 연결본 · 추출 본문 · 기관별 조례·지침 및 개별 적용 조건 별도 확인',
            paragraphs=len(text.splitlines()),collection='v40')
        if pages:
            row.update(annex=label.split(' ',2)[0]+' '+label.split(' ',2)[1],pdf_pages=pages,
                scope='공식 별표 PDF 전체 · 행 머리 공백 정리 · 표의 열·병합 및 비고는 원문 PDF와 함께 확인')
        rows.append(row)
    for key,title,label,institution in specs:
        reader=PdfReader(staging/downloads[key]['file'])
        text='\n'.join(p.extract_text(extraction_mode='layout') for p in reader.pages)
        compact=re.sub(r'\s+','',text)
        assert re.sub(r'\s+','',title) in compact and ('별표'+label.split(' ',2)[1]) in compact
        save(key,title,label,institution,text,'2026-10-02','대통령령 제36728호 · 현행 연결 별표',list(range(1,len(reader.pages)+1)))
    for key,title,number,effective in [
        *[(f'goods_decree_{n}',DECREE,n,'2026-06-03') for n in (30,64,65,67,68)],
        ('national_leave_20','국가공무원 복무규정',20,'2026-10-02')]:
        tree=Tree((staging/downloads[key]['file']).read_text(encoding='utf-8'));found=[]
        for node in tree.root.walk():
            if 'lawcon' not in node.attrs.get('class','').split():continue
            ps=[p.text() for p in node.walk() if p.tag=='p' and p.text()]
            if ps and re.match(r'^제'+str(number)+r'조\(',ps[0]):found.append(ps)
        assert len(found)==1,(key,len(found))
        ps=found[0];label=re.match(r'^제\d+조\([^)]*\)',ps[0])[0]
        if key=='national_leave_20':ps=ps[:1] # Only the collected annex's enabling paragraph, not unrelated special-leave provisions.
        save(key,title,label,'국가공무원' if key=='national_leave_20' else '지방자치단체 물품·계약업무',
             '\n'.join(ps),effective,'대통령령 제36728호' if key=='national_leave_20' else '대통령령 제36338호')
    assert len(rows)==11 and len({r['sha256'] for r in records+rows})==len(records)+11
    path.write_text(json.dumps(records+rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (BASE/'extended_downloads.json').write_text(json.dumps([downloads[key] for key in used_keys],ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Prepared',len(rows),'extended official excerpts; total',len(records+rows))


if __name__=='__main__':build()
