"""Installation/volume identity and the provenance of a stopped-volume backup."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import tarfile
import uuid

MAX_BACKUP_AGE = timedelta(hours=1)
CLOCK_SKEW = timedelta(minutes=5)
IDENTITY_FIELDS = ('installation_id', 'installation_created_at', 'environment', 'volume_name', 'binding_revision')


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Identity/backup timestamp is missing.')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Identity/backup timestamp must include a timezone.')
    return result.astimezone(timezone.utc)


def checked_binding(environment, volume):
    if environment == 'development' and volume is None:
        return
    if environment not in ('preview', 'production') or not isinstance(volume, str) or not re.fullmatch('gongmudam-' + environment + r'-[a-z0-9-]+', volume):
        raise ValueError('Bind a preview/production installation to its matching explicit volume name.')


def new_identity(environment='development', volume=None):
    checked_binding(environment, volume)
    return {'installation_id': str(uuid.uuid4()), 'installation_created_at': utc_now().isoformat(),
            'environment': environment, 'volume_name': volume, 'binding_revision': 0 if volume is None else 1,
            'restore_history': []}


def installation(marker):
    value = {key: marker.get(key) for key in IDENTITY_FIELDS}
    try:
        if str(uuid.UUID(value['installation_id'])) != value['installation_id']:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError('Installation identity is missing; explicitly bind the existing owned volume first.') from error
    timestamp(value['installation_created_at'])
    checked_binding(value['environment'], value['volume_name'])
    revision = value['binding_revision']
    if type(revision) is not int or revision < (0 if value['volume_name'] is None else 1):
        raise ValueError('Invalid installation binding revision.')
    return value


def inspect_descriptor(marker):
    return {'status': 'installation_inspected', **installation(marker),
            'last_restore': (marker.get('restore_history') or [None])[-1],
            'inspected_at': utc_now().isoformat()}


def archive_context(archive):
    """Read provenance from the actual archive, not only its separate receipt."""
    with tarfile.open(archive, 'r:gz') as tar:
        context = {}
        for name in ('backup-manifest.json', 'cloud-installation.json'):
            matches = [item for item in tar.getmembers() if item.name == name]
            if len(matches) != 1 or not matches[0].isfile() or matches[0].size > 1024 * 1024:
                raise ValueError('Backup identity metadata is invalid.')
            context[name] = tar.extractfile(matches[0]).read()
    manifest = json.loads(context['backup-manifest.json'])
    if manifest.get('format') != 2 or manifest.get('data_format') != 1:
        raise ValueError('Legacy backups remain restorable but cannot authorize a production deployment.')
    marker = json.loads(context['cloud-installation.json'])
    source = installation(marker)
    metadata = manifest.get('backup')
    if not isinstance(metadata, dict) or metadata.get('installation') != source:
        raise ValueError('Backup manifest and installation identity disagree.')
    expected = manifest['files'].get('cloud-installation.json', {})
    if (expected.get('sha256') != hashlib.sha256(context['cloud-installation.json']).hexdigest() or
            expected.get('bytes') != len(context['cloud-installation.json'])):
        raise ValueError('Backup installation marker integrity mismatch.')
    try:
        uuid.UUID(metadata['backup_id'])
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ValueError('Backup identity is invalid.') from error
    started, completed = timestamp(metadata.get('started_at')), timestamp(metadata.get('completed_at'))
    if started < timestamp(source['installation_created_at']) or completed < started:
        raise ValueError('Backup acquisition timestamps are inconsistent.')
    return metadata


def validate_production_backup(archive, receipt, target, *, volume, archive_sha256, now=None):
    now = now or utc_now()
    if (receipt.get('status') != 'backed_up' or receipt.get('data_format') != 1 or
            receipt.get('sha256') != archive_sha256):
        raise ValueError('Consistent backup receipt/archive verification failed.')
    metadata = archive_context(archive)
    if receipt.get('backup') != metadata:
        raise ValueError('Backup receipt does not describe the actual archived installation.')
    source, current = metadata['installation'], installation(target)
    if target.get('status') != 'installation_inspected':
        raise ValueError('Inspect the selected production installation after taking its backup.')
    if source['environment'] != 'production' or current['environment'] != 'production' or current['volume_name'] != volume:
        raise ValueError('A backup from another environment/volume cannot authorize this production target.')
    if (source['installation_id'], source['installation_created_at']) != (current['installation_id'], current['installation_created_at']):
        raise ValueError('Backup belongs to a different installation.')
    completed = timestamp(metadata['completed_at'])
    inspected = timestamp(target.get('inspected_at'))
    if completed > now + CLOCK_SKEW or inspected > now + CLOCK_SKEW or inspected < completed:
        raise ValueError('Backup/target inspection acquisition time is invalid.')
    if now - timestamp(metadata['started_at']) > MAX_BACKUP_AGE or now - inspected > MAX_BACKUP_AGE:
        raise ValueError('Production requires a stopped-volume backup and inspection from the last 60 minutes.')
    same_binding = (source['volume_name'], source['binding_revision']) == (current['volume_name'], current['binding_revision'])
    if not same_binding:
        restored = target.get('last_restore') or {}
        expected = {'backup_id': metadata['backup_id'], 'backup_sha256': archive_sha256,
                    'source_volume_name': source['volume_name'], 'source_binding_revision': source['binding_revision'],
                    'target_volume_name': current['volume_name'], 'target_binding_revision': current['binding_revision']}
        if any(restored.get(key) != value for key, value in expected.items()):
            raise ValueError('Backup does not match this replacement volume or its explicit restore history.')
        if timestamp(restored.get('restored_at')) < completed or timestamp(restored['restored_at']) > inspected:
            raise ValueError('Replacement-volume restore chronology is invalid.')
    return metadata
