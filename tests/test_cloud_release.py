"""Cloud release commands operate on a new, explicitly selected data volume."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CloudStateTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'tools/cloud_release.py'), *args],
                              cwd=ROOT, capture_output=True, text=True)

    def test_initialization_preserves_existing_work_and_rejects_unowned_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'
            first = self.run_cli('initialize', '--data-root', str(state))
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(json.loads(first.stdout)['status'], 'initialized')
            saved = state / 'data' / 'user-note.txt'
            saved.write_text('saved work', encoding='utf-8')
            again = self.run_cli('initialize', '--data-root', str(state))
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(json.loads(again.stdout)['status'], 'preserved')
            self.assertEqual(saved.read_text(encoding='utf-8'), 'saved work')
            unrelated = Path(tmp) / 'personal'
            unrelated.mkdir()
            (unrelated / 'config.json').write_text('private work', encoding='utf-8')
            refused = self.run_cli('initialize', '--data-root', str(unrelated))
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual((unrelated / 'config.json').read_text(), 'private work')

    def test_consistent_backup_roundtrip_preserves_files_and_rejects_bad_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state, recovered = root / 'state', root / 'recovered'
            self.assertEqual(self.run_cli('initialize', '--data-root', str(state)).returncode, 0)
            original = '합성 첨부의 원본 바이트'.encode()
            (state / 'data' / 'synthetic-attachment.txt').write_bytes(original)
            backup = root / 'backup.tar.gz'
            script = ROOT / 'tools/cloud_backup.py'
            saved = subprocess.run([sys.executable, str(script), 'backup', '--data-root', str(state), '--output', str(backup)],
                                   cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(saved.returncode, 0, saved.stderr)
            receipt = json.loads(saved.stdout)
            bad = subprocess.run([sys.executable, str(script), 'restore', '--archive', str(backup), '--sha256', '0' * 64,
                                  '--data-root', str(recovered)], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)
            self.assertFalse(recovered.exists())
            restored = subprocess.run([sys.executable, str(script), 'restore', '--archive', str(backup),
                                      '--sha256', receipt['sha256'], '--data-root', str(recovered)],
                                     cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual((recovered / 'data' / 'synthetic-attachment.txt').read_bytes(), original)
            again = subprocess.run([sys.executable, str(script), 'restore', '--archive', str(backup),
                                   '--sha256', receipt['sha256'], '--data-root', str(recovered)], cwd=ROOT, capture_output=True)
            self.assertNotEqual(again.returncode, 0)

    def test_missing_calendar_store_is_refused_instead_of_silently_recreated(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'
            initialized = self.run_cli('initialize', '--data-root', str(state))
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            calendar = state / 'data/calendar.db'
            self.assertTrue(calendar.is_file(), 'Explicit initialization must complete every persistent store.')
            calendar.unlink()
            refused = self.run_cli('initialize', '--data-root', str(state))
            self.assertNotEqual(refused.returncode, 0)
            self.assertFalse(calendar.exists())


if __name__ == '__main__':
    unittest.main()
