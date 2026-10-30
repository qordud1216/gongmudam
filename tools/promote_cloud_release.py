"""Plan/apply a verified image on an existing Docker host; never provisions accounts or initializes data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.cloud_release import verify_release


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def plan(release, environment, image_id, volume, runtime_env, *, preview=None,
         ui_note=None, backup_receipt=None, backup_archive=None):
    manifest = verify_release(release)
    if manifest.get('source_dirty') is not False:
        raise ValueError('Only a clean committed development release can be promoted.')
    identity = manifest['release_id']
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', image_id):
        raise ValueError('Use the immutable loaded Docker image ID, never a mutable tag.')
    if not re.fullmatch('gongmudam-' + environment + r'-[a-z0-9-]+', volume):
        raise ValueError('Choose a distinct volume named gongmudam-preview-* or gongmudam-production-*.')
    if not runtime_env.is_file():
        raise ValueError('Select the existing approved runtime env file; no credentials are created here.')
    if environment == 'production':
        if not preview or not ui_note or not ui_note.strip() or not backup_receipt or not backup_archive:
            raise ValueError('Production needs the matching preview HTTP receipt, an explicit UI verification note, and a consistent backup receipt/archive.')
        checked = json.loads(preview.read_text())
        if (checked.get('status') != 'preview_http_verified' or checked.get('release_id') != identity or
                checked.get('source_commit') != manifest['source_commit'] or
                checked.get('image_id') != image_id or
                checked.get('anonymous_access_rejected') is not True or checked.get('llm_enabled') is not False):
            raise ValueError('Preview receipt does not verify this exact release and source commit.')
        saved = json.loads(backup_receipt.read_text())
        if saved.get('status') != 'backed_up' or saved.get('data_format') != manifest['data_format'] or sha(backup_archive) != saved['sha256']:
            raise ValueError('Consistent backup receipt/archive verification failed.')
    return {'status': 'planned', 'environment': environment, 'release_id': identity,
            'source_commit': manifest['source_commit'], 'image_id': image_id, 'volume': volume,
            'data_initialization': False, 'database_migration': False,
            'external_ui_verification_note': ui_note if environment == 'production' else None}


def apply_plan(value, release, runtime_env):
    inspected = subprocess.run(['docker', 'image', 'inspect', value['image_id']], check=True, capture_output=True, text=True)
    labels = json.loads(inspected.stdout)[0]['Config'].get('Labels') or {}
    if labels.get('org.opencontainers.image.revision') != value['source_commit'] or labels.get('com.gongmudam.release') != value['release_id']:
        raise ValueError('Image provenance labels do not match the verified package.')
    env = dict(os.environ, GONGMUDAM_IMAGE=value['image_id'], GONGMUDAM_VOLUME_NAME=value['volume'],
               GONGMUDAM_RELEASE_ID=value['release_id'], GONGMUDAM_RUNTIME_ENV_FILE=str(runtime_env.resolve()))
    command = ['docker', 'compose', '-p', 'gongmudam-' + value['environment'], '-f', str(release / 'deploy/compose.yml')]
    if os.environ.get('CLOUDFLARED_TOKEN_FILE'):
        command += ['-f', str(release / 'deploy/compose.tunnel.yml')]
    subprocess.run(command + ['up', '-d', '--no-build', '--wait'], check=True, env=env)
    return value | {'status': 'host_started', 'external_url_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-directory', type=Path, required=True)
    parser.add_argument('--environment', choices=('preview', 'production'), required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--volume', required=True)
    parser.add_argument('--runtime-env-file', type=Path, required=True)
    parser.add_argument('--preview-receipt', type=Path)
    parser.add_argument('--ui-verification-note')
    parser.add_argument('--backup-receipt', type=Path)
    parser.add_argument('--backup-archive', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = plan(args.release_directory.resolve(), args.environment, args.image_id, args.volume,
                      args.runtime_env_file, preview=args.preview_receipt, ui_note=args.ui_verification_note,
                      backup_receipt=args.backup_receipt, backup_archive=args.backup_archive)
        if args.apply:
            result = apply_plan(result, args.release_directory.resolve(), args.runtime_env_file)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, 'Promotion stopped; inspect the selected artifacts/configuration. ' + type(error).__name__ + '\n')
    print(json.dumps(result, ensure_ascii=False))
