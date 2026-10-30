"""Read-only verification of an approved private preview; never prints Access credentials."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def verify(url, release_id, source_commit, image_id, output):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('Use the approved HTTPS preview origin without credentials, query or path.')
    token = os.environ.get('GONGMUDAM_ACCESS_JWT')
    if not token:
        raise ValueError('Supply an existing operator Access assertion via GONGMUDAM_ACCESS_JWT, never in command arguments or chat.')
    if output.exists():
        raise ValueError('Existing preview receipt will not be overwritten.')
    with httpx.Client(base_url=url.rstrip('/'), timeout=15, follow_redirects=False) as anonymous, \
            httpx.Client(base_url=url.rstrip('/'), headers={'Cf-Access-Jwt-Assertion': token}, timeout=15, follow_redirects=False) as owner:
        for path in ('/desktop/', '/api/home', '/api/documents/synthetic-probe/download', '/api/knowledge/sources/synthetic-probe/original'):
            if anonymous.get(path).status_code not in (302, 303, 401, 403):
                raise ValueError('Anonymous access was not rejected on every protected surface.')
        ready, status = owner.get('/health/ready'), owner.get('/api/cloud/status')
        if ready.status_code != 200 or status.status_code != 200:
            raise ValueError('Authenticated readiness/status failed. Inspect the approved Access route and backend.')
        for response in (ready, status):
            data = response.json()
            if (data.get('release_id') != release_id or data.get('source_commit') != source_commit or
                    data.get('image_id') != image_id or data.get('llm_enabled') is not False):
                raise ValueError('Preview release, source commit or no-LLM contract does not match.')
        desktop = owner.get('/desktop/')
        agencies = owner.get('/api/agencies', params={'q': '서울특별시'})
        if desktop.status_code != 200 or '/desktop/cloud.js' not in desktop.text or agencies.status_code != 200 or not agencies.json().get('items'):
            raise ValueError('Authenticated desktop/agency smoke check failed.')
    result = {'format': 1, 'status': 'preview_http_verified', 'preview_origin': url.rstrip('/'),
              'release_id': release_id, 'source_commit': source_commit, 'image_id': image_id, 'llm_enabled': False,
              'anonymous_access_rejected': True, 'manual_external_ui_verified': False,
              'verified_at': datetime.now(timezone.utc).isoformat()}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--release-id', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.url, args.release_id, args.source_commit, args.image_id, args.output), ensure_ascii=False))
