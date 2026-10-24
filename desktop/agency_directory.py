"""Read-only LEX-FLOW agency search contract for the standalone B desktop."""
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

REGIONS = ('서울특별시', '부산광역시', '대구광역시', '인천광역시', '광주광역시',
           '대전광역시', '울산광역시', '세종특별자치시', '경기도', '강원특별자치도',
           '충청북도', '충청남도', '전북특별자치도', '전라남도', '경상북도', '경상남도', '제주특별자치도')
FIELD_NAMES = {
    'full_name': 'fullName', 'short_name': 'shortName', 'parent_code': 'parentCode',
    'root_code': 'rootCode', 'representative_code': 'representativeCode',
    'type_large': 'typeLarge', 'type_large_name': 'typeLargeName',
    'type_medium': 'typeMedium', 'type_medium_name': 'typeMediumName',
    'type_small': 'typeSmall', 'type_small_name': 'typeSmallName',
    'created_at': 'createdAt', 'abolished_at': 'abolishedAt', 'changed_at': 'changedAt', 'previous_code': 'previousCode',
}


def convert(row):
    return {FIELD_NAMES.get(key, key): bool(value) if key == 'abolished' else value
            for key, value in dict(row).items()}


class AgencyDirectory:
    def __init__(self, path: Path):
        self.path = path.resolve()
        with closing(self.connect()) as db:
            self.source = json.loads(db.execute('SELECT payload FROM DIRECTORY_METADATA WHERE id=1').fetchone()[0])

    def connect(self):
        # This packaged snapshot is never updated in place or exposed as the live LEX database.
        db = sqlite3.connect(self.path.as_uri() + '?mode=ro&immutable=1', uri=True)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        return db

    def search(self, q: str, page=1, limit=8):
        q = q.strip()
        if len(q) > 100 or not 1 <= page <= 10000 or not 1 <= limit <= 30:
            raise ValueError('검색어와 조회 범위를 확인해 주세요.')
        if len(q) < 2:
            return {'items': [], 'total': 0, 'page': page, 'limit': limit, 'source': self.source}
        alias = re.sub(r'(시청|군청|구청)$', lambda m: {'시청': '시', '군청': '군', '구청': '구'}[m[0]], q)
        queries = list(dict.fromkeys((q, alias)))
        predicates, args = [], []
        exact, prefixes, paths = [], [], []
        exact_args, prefix_args, path_args = [], [], []
        for query in queries:
            literal = re.sub(r'([\\%_])', r'\\\1', query)
            if len(query) >= 3:
                fts = '"' + query.replace('"', '""') + '"'
                predicate = 'a.rowid IN (SELECT rowid FROM TB_AGENCY_FTS WHERE TB_AGENCY_FTS MATCH ?)'
                args.append(fts)
                if re.fullmatch('[A-Za-z0-9]+', query):
                    predicate = '(a.code>=? AND a.code<? OR ' + predicate + ')'
                    args[-1:] = [query.upper(), query.upper() + '\uffff', fts]
                predicates.append(predicate)
            else:
                predicates.append("(a.full_name LIKE ? ESCAPE '\\' OR a.short_name LIKE ? ESCAPE '\\' OR a.code LIKE ? ESCAPE '\\')")
                args.extend(('%' + literal + '%', literal + '%', literal.upper() + '%'))
            exact.append('(a.code=? OR a.full_name=? OR a.short_name=?)')
            exact_args.extend((query.upper(), query, query))
            if query == alias and alias != q:
                exact.append("a.full_name LIKE ? ESCAPE '\\'")
                exact_args.append('% ' + literal)
            prefixes.append("(a.short_name LIKE ? ESCAPE '\\' OR a.code LIKE ? ESCAPE '\\')")
            prefix_args.extend((literal + '%', literal.upper() + '%'))
            paths.append("(a.full_name LIKE ? ESCAPE '\\' OR a.full_name LIKE ? ESCAPE '\\')")
            path_args.extend((literal + '%', '% ' + literal + '%'))
        where = 'a.abolished=0 AND (' + ' OR '.join(predicates) + ')'
        ranking = ('CASE WHEN ' + ' OR '.join(exact) + ' THEN 0 WHEN ' + ' OR '.join(prefixes)
                   + ' THEN 1 WHEN ' + ' OR '.join(paths) + ' THEN 2 ELSE 3 END, '
                   "CASE WHEN a.type_medium_name='광역자치단체' AND substr(a.short_name,-1) IN ('시','도') THEN 0 "
                   "WHEN a.type_medium_name='기초자치단체' AND substr(a.short_name,-1) IN ('시','군','구') THEN 1 ELSE 2 END,")
        with closing(self.connect()) as db:
            total = db.execute('SELECT count(*) FROM TB_AGENCY a WHERE ' + where, args).fetchone()[0]
            rows = db.execute('SELECT a.* FROM TB_AGENCY a WHERE ' + where + ' ORDER BY ' + ranking + 'a.code LIMIT ? OFFSET ?',
                              args + exact_args + prefix_args + path_args + [limit, (page - 1) * limit])
            return {'items': [convert(row) for row in rows], 'total': total, 'page': page, 'limit': limit, 'source': self.source}

    def detail(self, code):
        if not re.fullmatch('[A-Z0-9]{7}', code):
            raise ValueError('기관코드를 확인해 주세요.')
        with closing(self.connect()) as db:
            def get(item_code):
                return db.execute('SELECT * FROM TB_AGENCY WHERE code=?', (item_code,)).fetchone()
            row = get(code)
            if not row:
                raise KeyError(code)
            item = convert(row)
            ancestors, seen, warnings = [], {code}, []
            parent = item['parentCode']
            while parent:
                if parent in seen or len(ancestors) >= 40:
                    warnings.append('상위기관 경로를 완전히 확인하지 못했습니다. 직접 확인해 주세요.')
                    break
                seen.add(parent)
                ancestor = get(parent)
                if not ancestor:
                    warnings.append('원본 자료에 상위기관 일부가 없습니다. 직접 확인해 주세요.')
                    break
                ancestors.insert(0, convert(ancestor))
                parent = ancestor['parent_code']
        current = [a for a in ancestors + [item] if not a['abolished']]
        sector = item['typeLarge'] or next((a['typeLarge'] for a in reversed(current) if a['typeLarge']), None)
        scope = 'local' if sector in ('02', '03') else 'national' if sector in ('01', '04', '05', '06', '18') else None
        metro = next((a for a in current if not a['parentCode'] and a['typeLarge'] == '02'
                      and a['typeMediumName'] == '광역자치단체' and a['fullName'] in REGIONS), None)
        region = {'name': metro['fullName'], 'basis': 'agency_hierarchy'} if metro else None
        if not region:
            # Only full official region names in actual path nodes; no city-name substring guessing.
            matches = {name for a in current for name in REGIONS if (a['shortName'] or a['fullName']).startswith(name)}
            if len(matches) == 1:
                region = {'name': matches.pop(), 'basis': 'official_name_prefix'}
        if not region:
            warnings.append('기관코드에서 소속 지역을 확인하지 못했습니다. 시·도를 직접 선택해 주세요.')
        if item['abolished']:
            warnings.append('폐지된 기관코드입니다. 현재 소속 기관을 다시 선택해 주세요.')
        return {'agency': item, 'ancestors': ancestors, 'context': {'scope': scope, 'region': region, 'warnings': warnings},
                'source': self.source}
