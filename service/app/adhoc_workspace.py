"""Read-only related-folder lookup for an existing collection job."""
from urllib.parse import quote
import json
import sqlite3
from . import folders


def related_folders(job_id: str) -> dict:
    """Return links and separate folder projects without initializing storage."""
    DB_PATH = folders.DB_PATH
    if not DB_PATH.exists():
        return {'job_id': job_id, 'linked': [], 'available': []}

    uri = DB_PATH.resolve().as_uri() + '?mode=ro'
    c = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        c.row_factory = sqlite3.Row
        row = c.execute('SELECT id,version,payload FROM libraries ORDER BY rowid').fetchall()
    except sqlite3.OperationalError as exc:
        if 'no such table: libraries' in str(exc).lower():
            return {'job_id': job_id, 'linked': [], 'available': []}
        raise
    finally:
        c.close()

    linked, available = [], []
    for library in row:
        payload = json.loads(library['payload'])
        files = payload.get('files') or {}
        if not isinstance(files, dict):
            files = {}
        projects = payload.get('projects') or {}
        if not isinstance(projects, dict):
            continue
        for project_id, project in projects.items():
            if not isinstance(project, dict):
                continue
            assigned = []
            for file_id, file in files.items():
                if isinstance(file, dict) and project_id in (file.get('project_ids') or []):
                    assigned.append({
                        'id': file_id,
                        'name': file.get('name', ''),
                        'present': bool(file.get('present')),
                        'changed': bool(file.get('changed')),
                    })
            descriptor = {
                'library_id': library['id'],
                'library_name': payload.get('name', ''),
                'project_id': project_id,
                'project_name': project.get('name', ''),
                'library_version': library['version'],
                'file_count': sum(f['present'] for f in assigned),
                'missing_count': sum(not f['present'] for f in assigned),
                'files': assigned,
                'href': f"folders.html#{quote(library['id'], safe='')}",
            }
            links = project.get('links') or []
            if isinstance(links, list) and any(
                isinstance(link, dict) and link.get('job_id') == job_id for link in links
            ):
                linked.append(descriptor)
            else:
                available.append(descriptor | {'files': []})
    return {'job_id': job_id, 'linked': linked, 'available': available}
