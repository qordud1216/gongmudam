"""검수한 별표 전사본과 공식 등록 원본의 연결·무결성. 금액 계산에 LLM을 사용하지 않는다."""
from pathlib import Path
import copy
import hashlib
import json

from . import official_sources

ROOT = Path(__file__).resolve().parents[1]


class RateTableError(ValueError):
    pass


def source_path(source):
    name = source['file']
    if not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name:
        raise RateTableError('보존 원문 파일 경로가 올바르지 않습니다.')
    collection = source.get('collection', 'travel')
    if collection not in ('travel', 'official-20261020', 'travel-recheck-20261020'):
        raise RateTableError('지원하지 않는 원문 보관 위치입니다.')
    return ROOT / 'reference_data' / collection / name


def verify_sources(pack, source_ids):
    for key in dict.fromkeys(source_ids):
        try:
            source = pack['sources'][key]
            if hashlib.sha256(source_path(source).read_bytes()).hexdigest() != source['sha256']:
                raise RateTableError('보존 원문 해시가 다릅니다: ' + source['title'])
        except (KeyError, OSError) as exc:
            raise RateTableError('계산 근거 원문이 없거나 손상되었습니다: ' + key) from exc


def checked_table(pack):
    table = pack.get('domestic_table')
    if table is None:
        # 기존 저장 건의 사본에는 새 지급 구분을 소급 추가하지 않는다.
        return None
    try:
        digest = hashlib.sha256(json.dumps(table, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if digest != pack['domestic_table_sha256'] or table['schema_version'] != 1 or table['currency'] != 'KRW':
            raise RateTableError('검수한 금액표 사본이 변경되었습니다. 배포본을 다시 검수하세요.')
        if set(table['source_ids']) != {'travel_annex1', 'travel_annex2'}:
            raise RateTableError('지급 구분표와 국내 금액표 연결이 필요합니다.')
        for key in table['source_ids']:
            row = official_sources.metadata(table['source_excerpt_sha256'][key])
            src = pack['sources'][key]
            if not row or src['excerpt_sha256'] != row['sha256'] or src['sha256'] != row['raw_sha256'] or src['url'] != row['source_url'] or src['file'] != row['raw_file'] or src['effective_date'] != row['effective_date']:
                raise RateTableError('등록한 공식 별표와 계산 금액표가 일치하지 않습니다: ' + key)
        verify_sources(pack, table['source_ids'])
        if set(table['groups']) != {'group1', 'group2'} or set(table['regions']) != {'seoul', 'metropolitan', 'other'}:
            raise RateTableError('금액표 지급 구분·지역 구조를 확인하세요.')
        return table
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, RateTableError):
            raise
        raise RateTableError('계산 금액표의 구조 또는 공식 등록 정보를 확인하세요.') from exc


def group_rates(pack, grade, table):
    if table is not None:
        return copy.deepcopy(table['groups'].get(grade))
    if grade == 'group2':
        return {**copy.deepcopy(pack['rates']), 'label': '제2호', 'rail_class': '일반실',
                'lodging_mode': 'capped_actual', 'clause_id': 'T2'}
    return None


def table_view(pack):
    if not pack:
        return None
    try:
        table = checked_table(pack)
        return dict(available=True, registered=table is not None, version=pack['version'],
                    coverage_start=pack['coverage_start'], verified_through=pack['verified_through'],
                    validity_policy=copy.deepcopy(pack.get('validity_policy')),
                    groups=copy.deepcopy(table['groups']) if table else {'group2': group_rates(pack, 'group2', None)},
                    regions=copy.deepcopy(table['regions']) if table else dict(seoul='서울특별시', metropolitan='광역시', other='그 밖의 지역'),
                    region_note=table['region_note'] if table else '저장 당시 규정팩의 지역별 상한을 적용합니다.')
    except RateTableError as exc:
        return dict(available=False, version=pack['version'], message=str(exc), groups={}, regions={})
