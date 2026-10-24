"""Behavior checks against the exported public agency snapshot, without touching LEX-FLOW."""
import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agency_directory import AgencyDirectory


class DirectoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = AgencyDirectory(ROOT / 'data/agencies-v1.sqlite')

    def test_city_hall_alias_ranks_official_city_first(self):
        result = self.directory.search('양주시청')
        self.assertGreater(result['total'], 0)
        self.assertEqual(result['items'][0]['code'], '5590000')
        self.assertFalse(result['items'][0]['abolished'])

    def test_parent_path_supplies_local_region_without_personnel_status(self):
        detail = self.directory.detail('5590000')
        self.assertEqual(detail['agency']['parentCode'], '6410000')
        self.assertEqual(detail['ancestors'][-1]['fullName'], '경기도')
        self.assertEqual(detail['context']['region'], {'name': '경기도', 'basis': 'agency_hierarchy'})
        self.assertNotIn('personnel_framework', detail['context'])

    def test_national_ministry_does_not_invent_location(self):
        items = self.directory.search('행정안전부')['items']
        ministry = next(item for item in items if item['fullName'] == '행정안전부')
        detail = self.directory.detail(ministry['code'])
        self.assertIsNone(detail['context']['region'])
        self.assertIsNone(detail['agency']['parentCode'])
        self.assertTrue(detail['context']['warnings'])

    def test_duplicate_names_keep_qualified_names_and_paging(self):
        first = self.directory.search('중구', limit=8)
        second = self.directory.search('중구', page=2, limit=8)
        self.assertGreater(first['total'], 8)
        self.assertTrue(set(x['code'] for x in first['items']).isdisjoint(x['code'] for x in second['items']))
        self.assertTrue(all(isinstance(x['code'], str) and len(x['code']) == 7 for x in first['items']))

    def test_search_special_characters_are_literals(self):
        for q in ['%_', '"""', "'; DROP TABLE TB_AGENCY;--", '\\%']:
            result = self.directory.search(q)
            self.assertIsInstance(result['items'], list)
        self.assertEqual(self.directory.search('%_')['total'], 0)
        self.assertEqual(self.directory.search('5590000')['items'][0]['code'], '5590000')

    def test_invalid_codes_and_ranges(self):
        for code in ('559000', '../data', '5590000?'):
            with self.assertRaises(ValueError):
                self.directory.detail(code)
        with self.assertRaises(ValueError):
            self.directory.search('경기도', page=0)

    def test_alphanumeric_agency_codes_stay_strings(self):
        result = self.directory.search('D091952')
        self.assertEqual(result['items'][0]['code'], 'D091952')
        self.assertEqual(self.directory.detail('D091952')['agency']['code'], 'D091952')

    def test_snapshot_only_contains_directory_tables_and_is_readonly(self):
        db = self.directory.connect()
        try:
            self.assertEqual(db.execute('SELECT count(*) FROM TB_AGENCY WHERE abolished=0').fetchone()[0], 133746)
            tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            self.assertTrue(all(name.startswith('TB_AGENCY') or name == 'DIRECTORY_METADATA' for name in tables))
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("UPDATE TB_AGENCY SET short_name='test' WHERE code='5590000'")
        finally:
            db.close()
        self.assertEqual(self.directory.source['sourceUpdatedAt'], '2026-10-21')


if __name__ == '__main__':
    unittest.main(verbosity=2)
