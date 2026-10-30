"""Production accepts the exact preview image and a verified backup, never only matching labels."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PromotionTests(unittest.TestCase):
    def test_changed_image_cannot_reuse_preview_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = root / 'release'
            release.mkdir()
            source = release / 'source.txt'
            source.write_text('synthetic release input')
            manifest = dict(format=1, kind='derived-development-release', source_commit='a' * 40,
                            source_dirty=False, data_format=1,
                            files={'source.txt': hashlib.sha256(source.read_bytes()).hexdigest()})
            identity = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            manifest['release_id'] = identity
            (release / 'development-release.json').write_text(json.dumps(manifest))
            runtime = root / 'runtime.env'
            runtime.write_text('# synthetic configuration; never applied\n')
            original_image, rebuilt_image = 'sha256:' + '1' * 64, 'sha256:' + '2' * 64
            preview = root / 'preview.json'
            preview.write_text(json.dumps(dict(status='preview_http_verified', release_id=identity,
                source_commit='a' * 40, image_id=original_image, anonymous_access_rejected=True, llm_enabled=False)))
            archive = root / 'backup.tar.gz'
            archive.write_bytes(b'synthetic backup fixture, not restored')
            receipt = root / 'backup.json'
            receipt.write_text(json.dumps(dict(status='backed_up', data_format=1,
                                               sha256=hashlib.sha256(archive.read_bytes()).hexdigest())))
            base = [sys.executable, 'tools/promote_cloud_release.py', '--release-directory', str(release),
                    '--environment', 'production', '--volume', 'gongmudam-production-synthetic',
                    '--runtime-env-file', str(runtime), '--preview-receipt', str(preview),
                    '--ui-verification-note', 'synthetic fixture, never deployed',
                    '--backup-receipt', str(receipt), '--backup-archive', str(archive)]
            changed = subprocess.run(base + ['--image-id', rebuilt_image], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(changed.returncode, 0)
            same = subprocess.run(base + ['--image-id', original_image], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(same.returncode, 0, same.stderr)
            self.assertEqual(json.loads(same.stdout)['status'], 'planned')


if __name__ == '__main__':
    unittest.main()
