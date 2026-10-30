"""Cloud release commands operate on a new, explicitly selected data volume."""
import json
import hashlib
import io
import subprocess
import sys
import tempfile
import tarfile
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

    def test_legacy_owned_volume_is_explicitly_adopted_without_replacing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'
            self.assertEqual(self.run_cli('initialize', '--data-root', str(state)).returncode, 0)
            note = state / 'data/saved-note.txt'
            note.write_text('existing work')
            marker = state / 'cloud-installation.json'
            legacy = json.loads(marker.read_text())
            for key in ('installation_id', 'installation_created_at', 'environment', 'volume_name', 'binding_revision', 'restore_history'):
                legacy.pop(key, None)
            marker.write_text(json.dumps(legacy))
            args = ('bind-volume', '--data-root', str(state), '--environment', 'production', '--volume', 'gongmudam-production-adopted')
            bound = self.run_cli(*args)
            self.assertEqual(bound.returncode, 0, bound.stderr)
            identity = json.loads(bound.stdout)['installation_id']
            again = self.run_cli(*args)
            self.assertEqual(json.loads(again.stdout)['installation_id'], identity)
            refused = self.run_cli('bind-volume', '--data-root', str(state), '--environment', 'production', '--volume', 'gongmudam-production-different')
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(note.read_text(), 'existing work')

    def test_legacy_backup_remains_restorable_with_its_recovery_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state, recovered = root / 'state', root / 'recovered'
            self.assertEqual(self.run_cli('initialize', '--data-root', str(state)).returncode, 0)
            (state / 'data/saved-note.txt').write_text('legacy work')
            archive = root / 'new.tar.gz'
            made = subprocess.run([sys.executable, 'tools/cloud_backup.py', 'backup', '--data-root', str(state), '--output', str(archive)], cwd=ROOT, capture_output=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            old = root / 'synthetic-format1.tar.gz'
            with tarfile.open(archive, 'r:gz') as current:
                payloads = {entry.name: current.extractfile(entry).read() for entry in current.getmembers()}
            marker = json.loads(payloads['cloud-installation.json'])
            for key in ('installation_id', 'installation_created_at', 'environment', 'volume_name', 'binding_revision', 'restore_history'):
                marker.pop(key, None)
            payloads['cloud-installation.json'] = json.dumps(marker).encode()
            manifest = json.loads(payloads['backup-manifest.json'])
            manifest.update(format=1)
            manifest.pop('backup')
            manifest['files']['cloud-installation.json'] = {'bytes': len(payloads['cloud-installation.json']), 'sha256': hashlib.sha256(payloads['cloud-installation.json']).hexdigest()}
            payloads['backup-manifest.json'] = json.dumps(manifest).encode()
            with tarfile.open(old, 'w:gz') as legacy:
                for name, value in payloads.items():
                    entry = tarfile.TarInfo(name)
                    entry.size = len(value)
                    legacy.addfile(entry, io.BytesIO(value))
            old_hash = hashlib.sha256(old.read_bytes()).hexdigest()
            restore = subprocess.run([sys.executable, 'tools/cloud_backup.py', 'restore', '--archive', str(old), '--sha256', old_hash, '--data-root', str(recovered)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(restore.returncode, 0, restore.stderr)
            self.assertEqual((recovered / 'data/saved-note.txt').read_text(), 'legacy work')
            adopted = self.run_cli('bind-volume', '--data-root', str(recovered), '--environment', 'production', '--volume', 'gongmudam-production-recovered')
            self.assertEqual(adopted.returncode, 0, adopted.stderr)
            history = json.loads((recovered / 'cloud-installation.json').read_text())['restore_history']
            self.assertEqual(history[-1]['legacy_backup_sha256'], old_hash)
            self.assertEqual((state / 'data/saved-note.txt').read_text(), 'legacy work')


if __name__ == '__main__':
    unittest.main()
