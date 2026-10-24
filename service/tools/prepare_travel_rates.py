"""공식 등록 별표와 대조한 국내 금액표 배포본. 기존 출장의 규정 사본은 변경하지 않는다."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import official_sources

APPROVED = {
    'travel_annex1': '9c433624e0e46a1de2f68163ab4a43b9cf59e50d040389c9f7b30b374aae1d4b',
    'travel_annex2': '3df802c01e9114aeebe7121d9a4efc2f58f607daa11120cf97028589e928c516',
}


def build():
    previous = ROOT / 'app/rulepacks/domestic_training_2026_10.json'
    pack = json.loads(previous.read_text(encoding='utf-8'))
    pack.update(version='2026-10-20.1', engine_version='domestic-tables-2.0')
    # 금액표 확인일만으로 별도 지침·조례의 확인 기간을 늘리지 않는다.
    for source_id, digest in APPROVED.items():
        row = official_sources.metadata(digest)
        if not row:
            raise ValueError('공식 등록 원본 해시 불일치: ' + source_id)
        pack['sources'][source_id] = dict(
            id=source_id, title=row['title'] + ' ' + row['article'],
            version=row['publication'], effective_date=row['effective_date'],
            verified_on=row['retrieved_at'][:10], url=row['source_url'],
            original_url=row['download_url'], file=row['raw_file'],
            collection='official-20261020', sha256=row['raw_sha256'],
            excerpt_sha256=digest,
        )
    pack['clauses']['N3']['summary'] = '지급 구분은 별표 1로 확인한다. 기관 유형·직급 이름만으로 지급 구분을 자동 추정하지 않는다.'
    pack['clauses'].update({
        'T1': dict(id='T1', source_id='travel_annex1', article='별표 1 여비 지급 구분표',
                   summary='제1호 해당 공무원과 그 밖의 제2호를 구분한다. 담당자가 해당 여부를 확인한다.', pdf_page=1),
        'T2': dict(id='T2', source_id='travel_annex2', article='별표 2 및 비고 제1호·제5호·제6호',
                   summary='국내 일비·식비는 제1호·제2호 각 25,000원/일. 제1호 숙박은 실비, 제2호는 지역별 상한 내 실비. 대통령·국무총리의 일비·식비는 실비 예외.', pdf_page=1),
        'T2_GROUP1': dict(id='T2_GROUP1', source_id='travel_annex2', article='별표 2 제1호 및 비고 제1호·제6호',
                   summary='제1호: 철도 특실 기준 실비, 일비·식비 각 25,000원/일, 숙박 실비. 대통령·국무총리의 일비·식비는 실비로 별도 검토한다. 할인 가능 시 할인요금 적용.', pdf_page=1),
        'T2_GROUP2': dict(id='T2_GROUP2', source_id='travel_annex2', article='별표 2 제2호 및 비고 제5호·제6호',
                   summary='제2호: 철도 일반실 실비, 일비·식비 각 25,000원/일. 숙박 상한 서울 100,000원, 광역시 80,000원, 그 밖 70,000원/박. 통합특별시는 종전 지역 기준. 할인 가능 시 할인요금 적용.', pdf_page=1),
    })
    for profile in pack['profiles'].values():
        profile['source_ids'] += list(APPROVED)
        profile['scope_basis'] += ['T1']
    # PDF의 병합 열을 시각 대조한 전사본. 모델 생성값이나 사용자의 등록 금액을 실행하지 않는다.
    table = dict(
        schema_version=1, currency='KRW', source_ids=list(APPROVED),
        source_excerpt_sha256=APPROVED, method='reviewed_pdf_transcription',
        checked_on='2026-10-20',
        groups={
            'group1': dict(label='제1호 (대통령·국무총리 제외)', daily=25000, meal_daily=25000,
                           rail_class='특실', lodging_mode='actual', lodging_caps=None, clause_id='T2_GROUP1'),
            'group2': dict(label='제2호', daily=25000, meal_daily=25000,
                           rail_class='일반실', lodging_mode='capped_actual',
                           lodging_caps=dict(seoul=100000, metropolitan=80000, other=70000), clause_id='T2_GROUP2'),
        },
        regions=dict(seoul='서울특별시', metropolitan='광역시·종전 광주광역시',
                     other='그 밖의 지역·세종·제주·종전 전남 시군'),
        region_note='통합특별시는 별표 2 비고 제5호에 따라 종전 전라남도 시군·광주광역시로 구분합니다. 실제 숙박지를 확인하세요.',
    )
    pack['domestic_table'] = table
    pack['domestic_table_sha256'] = hashlib.sha256(json.dumps(table, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    target = ROOT / 'app/rulepacks/domestic_tables_2026_10.json'
    target.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(target.name, pack['version'], pack['domestic_table_sha256'])


if __name__ == '__main__':
    build()
