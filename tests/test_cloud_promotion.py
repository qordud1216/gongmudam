"""Production promotion uses genuine backups from its inspected installation."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.cloud_identity import utc_now
from tools.promote_cloud_release import plan, apply_plan

ROOT = Path(__file__).resolve().parents[1]


class PromotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.release = cls.root / 'release'
        cls.release.mkdir()
        source = cls.release / 'source.txt'
        source.write_text('synthetic release input')
        manifest = dict(format=1, kind='derived-development-release', source_commit='a' * 40,
                        source_dirty=False, data_format=1,
                        files={'source.txt': hashlib.sha256(source.read_bytes()).hexdigest()})
        cls.release_id = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        manifest['release_id'] = cls.release_id
        (cls.release / 'development-release.json').write_text(json.dumps(manifest))
        cls.runtime = cls.root / 'runtime.env'
        cls.runtime.write_text('# synthetic configuration; never deployed\n')
        cls.image = 'sha256:' + '1' * 64
        cls.preview_http = cls.root / 'preview-http.json'
        cls.preview_http.write_text(json.dumps(dict(status='preview_http_verified', release_id=cls.release_id,
            source_commit='a' * 40, image_id=cls.image, anonymous_access_rejected=True, llm_enabled=False)))
        cls.states = {}
        for name, environment in (('target', 'production'), ('other', 'production'), ('preview', 'preview')):
            state = cls.root / ('state-' + name)
            volume = f'gongmudam-{environment}-{name}'
            cls.command('tools/cloud_release.py', 'initialize', '--data-root', str(state), '--environment', environment, '--volume', volume)
            (state / 'data/synthetic-note.txt').write_text('saved ' + name)
            archive = cls.root / (name + '.tar.gz')
            receipt = cls.root / (name + '-backup.json')
            saved = cls.command('tools/cloud_backup.py', 'backup', '--data-root', str(state), '--output', str(archive))
            receipt.write_text(json.dumps(saved))
            inspected = cls.root / (name + '-target.json')
            inspected.write_text(json.dumps(cls.command('tools/cloud_release.py', 'inspect', '--data-root', str(state))))
            cls.states[name] = dict(state=state, volume=volume, archive=archive, receipt=receipt, inspection=inspected)

    @classmethod
    def command(cls, *args):
        result = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)

    def invoke(self, *, backup='target', target='target', volume=None, image=None, include_target=True):
        source, current = self.states[backup], self.states[target]
        args = [sys.executable, 'tools/promote_cloud_release.py', '--release-directory', str(self.release),
                '--environment', 'production', '--image-id', image or self.image,
                '--volume', volume or current['volume'], '--runtime-env-file', str(self.runtime),
                '--preview-receipt', str(self.preview_http), '--ui-verification-note', 'synthetic fixture, never deployed',
                '--backup-receipt', str(source['receipt']), '--backup-archive', str(source['archive'])]
        if include_target:
            args += ['--target-installation-receipt', str(current['inspection'])]
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)

    def plan_current(self):
        state = self.states['target']
        return plan(self.release, 'production', self.image, state['volume'], self.runtime,
                    preview=self.preview_http, ui_note='synthetic fixture only', backup_receipt=state['receipt'],
                    backup_archive=state['archive'], target_installation=state['inspection'])

    def test_same_installation_backup_and_exact_preview_image_are_accepted(self):
        good = self.invoke()
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(json.loads(good.stdout)['status'], 'planned')
        changed = self.invoke(image='sha256:' + '2' * 64)
        self.assertNotEqual(changed.returncode, 0)

    def test_genuine_preview_and_other_installation_backups_cannot_authorize_target(self):
        for source, expected in (('preview', 'environment/volume'), ('other', 'different installation')):
            with self.subTest(source=source):
                denied = self.invoke(backup=source)
                self.assertNotEqual(denied.returncode, 0)
                self.assertIn(expected, denied.stderr)

    def test_wrong_volume_or_missing_selected_installation_is_rejected(self):
        wrong = self.invoke(volume='gongmudam-production-wrong')
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn('environment/volume', wrong.stderr)
        missing = self.invoke(include_target=False)
        self.assertNotEqual(missing.returncode, 0)

    def test_preview_restore_cannot_relabel_itself_as_production(self):
        source = self.states['preview']
        receipt = json.loads(source['receipt'].read_text())
        destination = self.root / 'rejected-cross-environment'
        result = subprocess.run([sys.executable, 'tools/cloud_backup.py', 'restore', '--archive', str(source['archive']),
            '--sha256', receipt['sha256'], '--data-root', str(destination), '--environment', 'production',
            '--volume', 'gongmudam-production-cross-environment'], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Cross-environment', result.stderr)
        self.assertFalse(destination.exists())
        self.assertEqual((source['state'] / 'data/synthetic-note.txt').read_text(), 'saved preview')

    def test_old_or_future_acquisition_time_is_rejected_without_changing_backup(self):
        with patch('tools.cloud_identity.utc_now', return_value=utc_now() + timedelta(hours=2)):
            with self.assertRaisesRegex(ValueError, 'last 60 minutes'):
                self.plan_current()
        with patch('tools.cloud_identity.utc_now', return_value=utc_now() - timedelta(hours=1)):
            with self.assertRaisesRegex(ValueError, 'acquisition time'):
                self.plan_current()
        self.assertEqual(self.invoke().returncode, 0)

    def test_receipt_cannot_relabel_the_archived_installation(self):
        other = json.loads(self.states['other']['receipt'].read_text())
        target = json.loads(self.states['target']['receipt'].read_text())
        other['backup']['installation'] = target['backup']['installation']
        forged = self.root / 'synthetic-relabelled-receipt.json'
        forged.write_text(json.dumps(other))
        with self.assertRaisesRegex(ValueError, 'actual archived installation'):
            plan(self.release, 'production', self.image, self.states['target']['volume'], self.runtime,
                 preview=self.preview_http, ui_note='synthetic fixture only', backup_receipt=forged,
                 backup_archive=self.states['other']['archive'], target_installation=self.states['target']['inspection'])

    def test_restored_replacement_preserves_identity_data_and_can_be_promoted(self):
        old = self.states['target']
        saved = json.loads(old['receipt'].read_text())
        original_marker = (old['state'] / 'cloud-installation.json').read_bytes()
        recovered, volume = self.root / 'replacement', 'gongmudam-production-replacement'
        result = self.command('tools/cloud_backup.py', 'restore', '--archive', str(old['archive']), '--sha256', saved['sha256'],
                              '--data-root', str(recovered), '--environment', 'production', '--volume', volume)
        self.assertEqual(result['installation']['installation_id'], saved['backup']['installation']['installation_id'])
        self.assertEqual((recovered / 'data/synthetic-note.txt').read_text(), 'saved target')
        self.assertEqual((old['state'] / 'cloud-installation.json').read_bytes(), original_marker)
        inspection = self.root / 'replacement-target.json'
        inspection.write_text(json.dumps(self.command('tools/cloud_release.py', 'inspect', '--data-root', str(recovered))))
        value = plan(self.release, 'production', self.image, volume, self.runtime, preview=self.preview_http,
                     ui_note='synthetic fixture only', backup_receipt=old['receipt'], backup_archive=old['archive'],
                     target_installation=inspection)
        self.assertEqual(value['status'], 'planned')
        self.assertEqual(value['target_installation']['last_restore']['backup_sha256'], saved['sha256'])
        fresh = self.root / 'replacement-fresh.tar.gz'
        fresh_receipt = self.root / 'replacement-fresh.json'
        fresh_receipt.write_text(json.dumps(self.command('tools/cloud_backup.py', 'backup', '--data-root', str(recovered), '--output', str(fresh))))
        inspection.write_text(json.dumps(self.command('tools/cloud_release.py', 'inspect', '--data-root', str(recovered))))
        self.assertEqual(plan(self.release, 'production', self.image, volume, self.runtime,
            preview=self.preview_http, ui_note='synthetic fixture only', backup_receipt=fresh_receipt,
            backup_archive=fresh, target_installation=inspection)['status'], 'planned')

    def test_apply_rechecks_actual_selected_docker_installation_before_compose(self):
        value = self.plan_current()
        labels = {'org.opencontainers.image.revision': 'a' * 40, 'com.gongmudam.release': self.release_id}
        wrong = self.states['other']['inspection'].read_text()
        replies = [subprocess.CompletedProcess([], 0, json.dumps([{'Config': {'Labels': labels}}])),
                   subprocess.CompletedProcess([], 0, ''), subprocess.CompletedProcess([], 0, wrong)]
        with patch('tools.promote_cloud_release.subprocess.run', side_effect=replies) as run:
            with self.assertRaisesRegex(ValueError, 'selected|Selected'):
                apply_plan(value, self.release, self.runtime, backup_receipt=self.states['target']['receipt'],
                           backup_archive=self.states['target']['archive'])
        self.assertEqual(run.call_count, 3)

    def test_matching_actual_installation_reaches_compose_without_initializing_data(self):
        value = self.plan_current()
        labels = {'org.opencontainers.image.revision': 'a' * 40, 'com.gongmudam.release': self.release_id}
        actual = self.states['target']['inspection'].read_text()
        replies = [subprocess.CompletedProcess([], 0, json.dumps([{'Config': {'Labels': labels}}])),
                   subprocess.CompletedProcess([], 0, ''), subprocess.CompletedProcess([], 0, actual),
                   subprocess.CompletedProcess([], 0, '')]
        with patch('tools.promote_cloud_release.subprocess.run', side_effect=replies) as run:
            result = apply_plan(value, self.release, self.runtime, backup_receipt=self.states['target']['receipt'],
                                backup_archive=self.states['target']['archive'])
        self.assertEqual(result['status'], 'host_started')
        self.assertFalse(result['data_initialization'])
        self.assertIn('compose', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
