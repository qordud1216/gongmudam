"""Full-page manual payloads survive clean restore and relocation."""
import copy,json,shutil,sqlite3,tempfile,unittest,hashlib
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from app import folders,knowledge,manual_knowledge
from tools import restore_submission as restore,build_portable_submission as build
from test_portable_submission import make_root
from test_manual_knowledge import pdf_bytes

def add_manual(root):
    bundle_path=root/'submission-data/knowledge.json';bundle=json.loads(bundle_path.read_text(encoding='utf-8'))
    raw=pdf_bytes(23);digest=hashlib.sha256(raw).hexdigest()
    asset=f'submission-data/manuals/{digest}.pdf';path=root/asset;path.parent.mkdir();path.write_bytes(raw)
    entry=dict(id='manual-test',library_id='manual-library',file_id='manual-file',title='e-사람 사용자 매뉴얼.pdf',sha256=digest,
        kind='업무편람',institution='제공 파일',effective_date='',registered_at='2026-10-24',asset=asset,enabled=1,
        library_name='e-사람 매뉴얼 · 전체 페이지',reference_kind='system_manual',system='e-사람',local_only=True,scan_profile='direct-v63',limited=False,
        **manual_knowledge.extract_pdf(raw))
    bundle['sources'].append(entry);bundle_path.write_text(json.dumps(bundle,ensure_ascii=False),encoding='utf-8');return entry

def record(root):
    with closing(sqlite3.connect(root/'data/folders.db')) as c:
        source=json.loads(c.execute("SELECT payload FROM knowledge_sources WHERE id='manual-test'").fetchone()[0])
        lib=json.loads(c.execute("SELECT payload FROM libraries WHERE id='manual-library'").fetchone()[0])
    return source,lib

class PortableManualsTest(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.root=make_root(self.base);self.entry=add_manual(self.root)
    def tearDown(self):self.temp.cleanup()
    def test_clean_restore_preserves_full_pages_and_original_endpoint_boundary(self):
        restore.restore(self.root);source,library=record(self.root)
        self.assertEqual(source['units'],self.entry['units']);self.assertEqual(source['page_coverage'],self.entry['page_coverage'])
        self.assertEqual(source['indexed_pages'],23);self.assertEqual(source['reference_kind'],'system_manual')
        self.assertEqual(library['reference_kind'],'system_manual');self.assertEqual(library['files']['manual-file']['name'],self.entry['title'])
        self.assertEqual(library['files']['manual-file']['units'],[])
        self.assertTrue(Path(source['path']).is_relative_to(self.root/'data/manuals'))
        with patch.object(folders,'DB_PATH',self.root/'data/folders.db'):
            self.assertTrue(knowledge.current_source(source));r=knowledge.original_manual('manual-test')
            self.assertEqual(r.media_type,'application/pdf');self.assertEqual(build.sha(Path(r.path)),source['sha256'])
    def test_move_rebases_manual_keeps_identity_disabled_state_and_config(self):
        restore.restore(self.root)
        with closing(sqlite3.connect(self.root/'data/folders.db')) as c:
            with c:c.execute("UPDATE knowledge_sources SET enabled=0 WHERE id='manual-test'")
        cfg={'llm':{'active':'my-model'},'server':{'port':9999}};(self.root/'config.json').write_text(json.dumps(cfg),encoding='utf-8')
        moved=self.base/'다른 경로';shutil.copytree(self.root,moved)
        self.root.rename(self.base/'old-root-unavailable')
        self.assertEqual(restore.restore(moved)['status'],'rebased')
        source,library=record(moved)
        self.assertTrue(Path(source['path']).is_relative_to(moved/'data/manuals'));self.assertTrue(Path(source['path']).exists())
        self.assertEqual(source['units'],self.entry['units']);self.assertEqual(source['id'],'manual-test');self.assertEqual(library['reference_kind'],'system_manual')
        with closing(sqlite3.connect(moved/'data/folders.db')) as c:self.assertEqual(c.execute("SELECT enabled FROM knowledge_sources WHERE id='manual-test'").fetchone()[0],0)
        self.assertEqual(json.loads((moved/'config.json').read_text()),cfg)
    def test_export_manual_is_opt_in_and_preserves_page_metadata(self):
        restore.restore(self.root)
        plain=self.base/'plain';plain.mkdir();self.assertEqual(len(build.export_knowledge(self.root,plain)['sources']),1)
        selected=self.base/'selected';selected.mkdir();bundle=build.export_knowledge(self.root,selected,['manual-test'])
        entry=next(s for s in bundle['sources'] if s['id']=='manual-test')
        for name in ('reference_kind','units','page_count','indexed_pages','page_coverage','scan_profile','system'):
            self.assertEqual(entry[name],self.entry[name],name)
        self.assertNotIn('path',entry);self.assertEqual(build.sha(selected/entry['asset']),entry['sha256'])
        with self.assertRaises(ValueError):build.export_knowledge(self.root,self.base/'bad',['missing-manual'])
    def test_damaged_original_or_missing_page_metadata_refused_before_database_creation(self):
        path=self.root/self.entry['asset'];raw=path.read_bytes();path.write_bytes(b'bad')
        with self.assertRaises(ValueError):restore.restore(self.root)
        self.assertFalse((self.root/'data/folders.db').exists());path.write_bytes(raw)
        p=self.root/'submission-data/knowledge.json';bundle=json.loads(p.read_text(encoding='utf-8'));bundle['sources'][-1]['units'].pop();p.write_text(json.dumps(bundle),encoding='utf-8')
        with self.assertRaises(ValueError):restore.restore(self.root)
        self.assertFalse((self.root/'data/folders.db').exists())
    def test_modified_installed_manual_not_overwritten_during_move(self):
        restore.restore(self.root);moved=self.base/'moved';shutil.copytree(self.root,moved)
        source,_=record(moved);target=moved/Path(source['path']).relative_to(self.root);target.write_bytes(b'user-edited')
        with self.assertRaises(ValueError):restore.restore(moved)
        self.assertEqual(target.read_bytes(),b'user-edited')
    def test_same_root_rerun_rejects_missing_or_modified_manual(self):
        for state in ('missing', 'modified'):
            with self.subTest(state=state):
                root=self.base/state;shutil.copytree(self.root,root)
                restore.restore(root)
                source,_=record(root);target=Path(source['path'])
                if state=='missing':target.unlink()
                else:target.write_bytes(b'changed')
                db=root/'data/folders.db';before=db.read_bytes()
                with self.assertRaises(ValueError):restore.restore(root)
                self.assertEqual(db.read_bytes(),before)
                if state=='missing':self.assertFalse(target.exists())
                else:self.assertEqual(target.read_bytes(),b'changed')

if __name__=='__main__':unittest.main()
