"""Render a non-routed private Worker configuration from approved existing identifiers."""
import argparse
import json
import os
from pathlib import Path
import re


def render(output, release_id, environment):
    if environment not in ('preview', 'production') or not re.fullmatch('[a-f0-9]{64}', release_id):
        raise ValueError('Select preview/production and a verified release ID.')
    account = os.environ.get('CLOUDFLARE_ACCOUNT_ID', '')
    service = os.environ.get('GONGMUDAM_VPC_SERVICE_ID', '')
    name = os.environ.get('GONGMUDAM_WORKER_NAME', '')
    if not re.fullmatch('[a-f0-9]{32}', account) or not re.fullmatch('[a-f0-9-]{32,36}', service):
        raise ValueError('Configure approved CLOUDFLARE_ACCOUNT_ID and GONGMUDAM_VPC_SERVICE_ID.')
    if not re.fullmatch('[a-z0-9-]{3,63}', name):
        raise ValueError('Configure a distinct GONGMUDAM_WORKER_NAME for this environment.')
    # Routes/Access are configured and verified separately, before enabling visitors.
    value = {'name': name, 'account_id': account, 'main': str(Path(__file__).resolve().parents[1] / 'cloudflare/cloud-worker.js'),
             'compatibility_date': '2026-10-30', 'workers_dev': False, 'preview_urls': False,
             'routes': [], 'vars': {'RELEASE_ID': release_id, 'RELEASE_ENVIRONMENT': environment},
             'vpc_services': [{'binding': 'BACKEND', 'service_id': service}]}
    if output.exists():
        raise ValueError('Existing configuration will not be overwritten.')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2) + '\n')
    return {'status': 'rendered_without_public_routes', 'environment': environment, 'release_id': release_id}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--release-id', required=True)
    parser.add_argument('--environment', choices=('preview', 'production'), required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.output, args.release_id, args.environment)))
