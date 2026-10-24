import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app import official_sources as o
from tools.prepare_official_pack import Tree,articles,BASE

class OfficialSourcesTest(unittest.TestCase):
    def test_inline_whitespace_preserved(self):
        self.assertEqual(Tree('<p>규정과<a> 같은 법</a> 시행령</p>').root.text(),'규정과 같은 법 시행령')
    def test_image_alt_text_preserved(self):
        self.assertEqual(Tree('<p>표 <img alt="6년 이상 21" /></p>').root.text(),'표 6년 이상 21')
    def test_collected_articles_match_hashes_and_expected_versions(self):
        rows=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(rows),14)
        self.assertEqual(len({r['sha256'] for r in rows}),len(rows))
        self.assertEqual(sum(r.get('budget_scope')=='local_government' for r in rows),2)
        for r in rows:
            m=o.metadata(r['sha256']);self.assertIsNotNone(m);self.assertLessEqual(m['effective_date'],'2026-10-20')
            excerpt=(BASE/'excerpts'/r['filename']).read_text(encoding='utf-8')
            if r.get('collection')=='v40' and r.get('annex'):
                normalized_excerpt=' '.join(excerpt.split())
                self.assertIn(' '.join(r['annex'].split()),normalized_excerpt)
                article_title=r['article'].removeprefix(r['annex']).strip()
                if article_title:
                    self.assertIn(' '.join(article_title.split()),normalized_excerpt)
            else:
                self.assertIn(r['article'],excerpt)
    def test_unknown_digest_does_not_gain_official_label(self):self.assertIsNone(o.metadata('0'*64))
    def test_raw_mutation_invalidates_metadata(self):
        with tempfile.TemporaryDirectory() as d,patch.object(o,'BASE',Path(d)):
            p=Path(d);(p/'excerpts').mkdir();(p/'excerpts/a.txt').write_text('原文',encoding='utf-8');(p/'raw.html').write_bytes(b'changed')
            sha=hashlib.sha256((p/'excerpts/a.txt').read_bytes()).hexdigest()
            (p/'manifest.json').write_text(json.dumps([dict(sha256=sha,filename='a.txt',raw_file='raw.html',raw_sha256=hashlib.sha256(b'original').hexdigest(),source_url='https://www.law.go.kr/example')]),encoding='utf-8')
            self.assertIsNone(o.metadata(sha))
