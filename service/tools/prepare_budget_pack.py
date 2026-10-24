"""Reproducible excerpts of the reviewed 2026 MOIS budget table, preserving original text."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'reference_data/official-20261020'
PAGE_URL = 'https://www.mois.go.kr/frt/bbs/type001/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000016&nttId=119443'
PDF_URL = 'https://www.mois.go.kr/cmm/fms/FileDown.do?atchFileId=FILE_00137730ECcmNP8&fileSn=1'


def build():
    raw = BASE / 'local_budget_2026.pdf'
    reader = PdfReader(raw)
    page = lambda number: reader.pages[number - 1].extract_text()
    assert '2026년도 지방자치단체' in ' '.join(page(n) for n in [1,2,3,4])
    assert '이 훈령은 2026년도' in page(30)
    assert '별표 11' in page(85)
    office = page(87).split('200물건비\n', 1)[1]
    continuation = page(88).split('200 201일반운영비 ', 1)[1].split('\n바.', 1)[0]
    assets = '405자산취득비 ' + page(114).split('405자산취득비 ', 1)[1].split('\n02.도서구입비', 1)[0]
    data = [('01.사무관리비', '사무관리비_2026.txt', office + '\n' + continuation + '\n', [87,88]),
            ('01.자산및물품취득비', '자산및물품취득비_2026.txt', assets + '\n', [114])]
    manifest = BASE / 'manifest.json'
    records = [r for r in json.loads(manifest.read_text(encoding='utf-8')) if not r.get('budget_scope')]
    raw_sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    for article, filename, text, pages in data:
        # The registered TXT reader trims line indentation. Normalize it once in the saved excerpt too.
        text='\n'.join(line.strip() for line in text.splitlines())+'\n'
        target = BASE / 'excerpts' / filename
        target.write_text(text, encoding='utf-8')
        records.append(dict(title='지방자치단체 예산편성 운영기준', article=article,
            annex='별표 11 세출예산 성질별 분류', effective_date='2025-07-31', publication='행정안전부훈령 제404호 · 2026년도 자료',
            issuer='행정안전부', institution='지방자치단체 2026년도 예산 · 국가·교육비특별회계 등 별도 기준 확인', kind='기관 지침',
            source_url=PAGE_URL, download_url=PDF_URL + '#page=' + str(pages[0]),
            retrieved_at=datetime.now(timezone.utc).isoformat(), raw_file=raw.name, raw_sha256=raw_sha,
            filename=filename, sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            scope=f'별표 11 표 발췌 · PDF {"·".join(map(str,pages))}쪽 · 행 머리 공백 정리 · 2026년도 적용 자료 · 기관의 실제 예산·품목 확인 필요',
            paragraphs=len(text.splitlines()), budget_scope='local_government', budget_topics=['office_supplies' if pages==[87,88] else 'assets'],
            fiscal_years=[2026], pdf_pages=pages))
    manifest.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Prepared 2 budget excerpts; total', len(records))


if __name__ == '__main__':
    build()
