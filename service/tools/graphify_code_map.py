"""Maintain a code-only Graphify snapshot outside the application runtime."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
PILOT = PROJECT.parent / 'work' / 'graphify-pilot-20261023'
WORKSPACE = PROJECT.parent / 'work' / 'graphify-seomu-maintenance'
RUNTIME = Path(os.environ.get('SEOMU_GRAPHIFY_PYTHON', str(PILOT / '.venv/Scripts/python.exe')))
ASSET = Path(os.environ.get('SEOMU_GRAPHIFY_ASSET', str(PILOT / 'graphify-out/assets/vis-network.min.js')))
SCOPES = {'app': '.py', 'static': '.js', 'tests': '.py'}
ARTIFACTS = ('graph.json', 'graph.html', 'GRAPH_REPORT.md', 'graph-health.json',
             '.graphify_extract.json', '.graphify_analysis.json',
             'assets/vis-network.min.js')
VENDOR = 'https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js'
ASSET_SHA256 = '576bb887733eb01bb52ee75b90ef46d818454de5fddb5b616fb8a298d307ca12'


def digest(content):
    return hashlib.sha256(content).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def source_snapshot(project):
    """Read only approved source extensions; never traverse linked folders."""
    result = {}
    project = project.resolve()
    # Bundled third-party engines are integrity-checked assets, not application code.
    asset_roots = {'static/toolbox/vendor', 'static/toolbox/ocr', 'static/lib/calendar'}
    for directory, suffix in SCOPES.items():
        base = project / directory
        if not base.exists() or linked(base):
            continue
        for parent, folders, files in os.walk(base, followlinks=False):
            folders[:] = sorted(n for n in folders if n != '__pycache__'
                                and (Path(parent) / n).relative_to(project).as_posix() not in asset_roots
                                and not linked(Path(parent) / n))
            for name in sorted(files):
                file = Path(parent) / name
                if file.suffix != suffix or linked(file):
                    continue
                if not file.resolve().is_relative_to(project):
                    raise RuntimeError(f'Source escapes project: {file}')
                result[file.relative_to(project).as_posix()] = file.read_bytes()
    return result


class CodeMap:
    def __init__(self, project=PROJECT, workspace=WORKSPACE, runtime=RUNTIME, asset=ASSET):
        self.project = Path(project).resolve()
        if linked(Path(workspace)):
            raise RuntimeError('Linked development workspace rejected.')
        self.folder = Path(workspace).resolve()
        self.runtime = Path(runtime).resolve()
        self.asset = Path(asset).resolve()
        if (self.folder.is_relative_to(self.project) or self.project.is_relative_to(self.folder)
                or self.folder.is_relative_to(PILOT.resolve())):
            raise RuntimeError('Use a separate development workspace outside the app and original pilot.')
        self.corpus = self.folder / 'corpus'
        self.out = self.folder / 'graphify-out'
        self.state = self.folder / 'state.json'
        self.pending = self.folder / 'refresh-incomplete.json'
        self.validate_workspace()

    def validate_workspace(self):
        # This private snapshot/cache folder must contain ordinary paths only.
        # Check before any stale-file deletion, output rewrite or lock-file open.
        for parent, folders, files in os.walk(self.folder, followlinks=False):
            for name in folders + files:
                if linked(Path(parent) / name):
                    raise RuntimeError(f'Linked development path rejected: {Path(parent) / name}')

    def snapshot(self):
        return source_snapshot(self.project)

    def status(self, snapshot=None):
        snapshot = self.snapshot() if snapshot is None else snapshot
        hashes = {n: digest(b) for n, b in snapshot.items()}
        try:
            state = read_json(self.state)
            def valid_hashes(value):
                return isinstance(value, dict) and all(
                    isinstance(k, str) and isinstance(v, str) and len(v) == 64
                    and all(c in '0123456789abcdef' for c in v) for k, v in value.items())
            if (not isinstance(state, dict) or state.get('project') != str(self.project)
                    or state.get('schema') != 1 or not valid_hashes(state.get('sources'))
                    or not valid_hashes(state.get('artifacts'))
                    or set(state['artifacts']) != set(ARTIFACTS)):
                state = {}
        except (OSError, ValueError):
            state = {}
        previous = state.get('sources', {})
        added = sorted(hashes.keys() - previous.keys())
        removed = sorted(previous.keys() - hashes.keys())
        changed = sorted(n for n in hashes.keys() & previous.keys() if hashes[n] != previous[n])
        artifacts_ok = bool(state.get('artifacts')) and all(
            (self.out / n).is_file() and digest((self.out / n).read_bytes()) == h
            for n, h in state.get('artifacts', {}).items())
        copy_ok = {n: digest(b) for n, b in source_snapshot(self.corpus).items()} == hashes
        fresh = bool(state) and not (added or removed or changed or self.pending.exists()) and artifacts_ok and copy_ok
        return dict(fresh=fresh, workspace=str(self.folder), graph=str(self.out / 'graph.html'),
                    source_files=len(hashes), added=added, changed=changed, removed=removed,
                    artifacts_match=artifacts_ok, copy_matches=copy_ok,
                    refresh_incomplete=self.pending.exists(), runtime_available=self.runtime.is_file(),
                    updated_at=state.get('updated_at'))

    @contextmanager
    def locked(self):
        self.validate_workspace()
        self.folder.mkdir(parents=True, exist_ok=True)
        with (self.folder / 'workflow.lock').open('a+b') as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError('Another Graphify command is running; retry after it finishes.') from exc
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def child(self, mode, *args):
        if not self.runtime.is_file():
            raise RuntimeError('Isolated Graphify Python missing. Set SEOMU_GRAPHIFY_PYTHON; see docs/Graphify_개발절차.md.')
        env = dict(os.environ, GRAPHIFY_BACKEND='none', GRAPHIFY_OUT=str(self.out),
                   PYTHONIOENCODING='utf-8', SEOMU_GRAPHIFY_ASSET=str(self.asset))
        result = subprocess.run([str(self.runtime), str(Path(__file__).resolve()), mode,
                                 str(self.folder), *args], cwd=self.folder, env=env,
                                capture_output=True, text=True, encoding='utf-8')
        if result.returncode:
            raise RuntimeError((result.stderr + result.stdout)[-5000:])
        return result.stdout

    def refresh(self, force=False):
        self.validate_workspace()
        snapshot = self.snapshot()
        before = self.status(snapshot)
        if before['fresh'] and not force:
            return dict(before, rebuilt=False)
        if not snapshot:
            raise RuntimeError('No approved source files; refusing to replace the map with an empty snapshot.')
        self.folder.mkdir(parents=True, exist_ok=True)
        hashes = {n: digest(b) for n, b in snapshot.items()}
        write_json(self.pending, dict(schema=1, project=str(self.project), sources=hashes))
        # Delete only obsolete approved files in this disposable corpus, never directories.
        for name in source_snapshot(self.corpus).keys() - snapshot.keys():
            file = self.corpus / name
            if (not file.is_relative_to(self.corpus)
                    or not file.resolve().is_relative_to(self.folder / 'corpus')):
                raise RuntimeError('Obsolete snapshot path escapes corpus.')
            file.unlink()
        for name, content in snapshot.items():
            file = self.corpus / name
            if linked(file) or any(linked(p) for p in file.parents if p != self.folder and p.is_relative_to(self.folder)):
                raise RuntimeError('Linked snapshot destination rejected.')
            if not file.resolve().is_relative_to(self.corpus.resolve()):
                raise RuntimeError('Snapshot destination escapes corpus.')
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content)
        build_output = self.child('_build')
        if {n: digest(b) for n, b in self.snapshot().items()} != hashes:
            raise RuntimeError('Source changed during refresh; retry. Map is not marked fresh.')
        state = dict(schema=1, project=str(self.project), sources=hashes,
                     updated_at=datetime.now(timezone.utc).isoformat(),
                     artifacts={n: digest((self.out / n).read_bytes()) for n in ARTIFACTS})
        write_json(self.state, state)
        self.pending.unlink()
        result = self.status()
        if not result['fresh']:
            raise RuntimeError('Final freshness check failed; retry before using this graph.')
        return dict(result, rebuilt=True, build_output=build_output.strip())


def isolated_main(mode, workspace, args):
    folder = Path(workspace).resolve()
    layout = CodeMap(workspace=folder)
    out, corpus = layout.out, layout.corpus
    os.chdir(folder)
    os.environ['GRAPHIFY_BACKEND'] = 'none'
    os.environ['GRAPHIFY_OUT'] = str(out)
    attempts = []

    def audit(event, values):
        if event in ('socket.connect', 'socket.getaddrinfo'):
            attempts.append(event)
            raise RuntimeError('Network calls are disabled for code-map operations.')
    sys.addaudithook(audit)
    if importlib.metadata.version('graphifyy') != '0.9.94':
        raise RuntimeError('This workflow is verified with graphifyy==0.9.94; use a pinned isolated environment.')
    try:
        if mode == '_cli':
            if not args or args[0] not in ('query', 'explain', 'path'):
                raise RuntimeError('Unsupported read-only graph command.')
            sys.argv = ['graphify', *args]
            runpy.run_module('graphify', run_name='__main__')
            return
        from graphify.detect import detect, save_manifest
        from graphify.extract import extract
        from graphify.build import build_from_json
        from graphify.cluster import cluster, score_all
        from graphify.analyze import god_nodes, surprising_connections
        from graphify.export import to_json, to_html
        from graphify.report import generate
        from graphify.diagnostics import diagnose_extraction

        plan = read_json(layout.pending)
        asset = Path(os.environ['SEOMU_GRAPHIFY_ASSET']).read_bytes()
        if digest(asset) != ASSET_SHA256:
            raise RuntimeError('Offline graph asset hash mismatch.')
        detection = detect(corpus, cache_root=folder)
        paths = [Path(p) for p in detection['files']['code']]
        if (set(p.relative_to(corpus).as_posix() for p in paths) != set(plan['sources'])
                or any(v for k, v in detection['files'].items() if k != 'code')):
            raise RuntimeError('Unexpected files in the code-only snapshot.')
        extraction = extract(paths, cache_root=folder, root=corpus, parallel=False)
        if extraction.get('failed_sources') or extraction.get('skipped_sources'):
            raise RuntimeError('Extraction reported failed or skipped sources.')
        graph = build_from_json(extraction, directed=True, root=corpus)
        communities = cluster(graph)
        labels = {}
        for cid, nodes in communities.items():
            from collections import Counter
            names = Counter(Path(graph.nodes[n].get('source_file', 'external')).stem for n in nodes)
            labels[cid] = ' / '.join(n for n, _ in names.most_common(2))
        out.mkdir(parents=True, exist_ok=True)
        health = diagnose_extraction(extraction, directed=True, root=corpus)
        # This is a complete rebuild of the verified code-only snapshot. Deleted
        # sources legitimately shrink it; Graphify's default shrink guard would
        # retain stale nodes. Only this disposable development map is replaced.
        if not to_json(graph, communities, str(out / 'graph.json'),
                       community_labels=labels, force=True):
            raise RuntimeError('Graph export was refused; map is not marked fresh.')
        to_html(graph, communities, str(out / 'graph.html'), community_labels=labels)
        html = (out / 'graph.html').read_text(encoding='utf-8')
        native_tag = ('<script src="' + VENDOR + '"\n'
                      '        integrity="sha384-Ux6phic9PEHJ38YtrijhkzyJ8yQlH8i/+buBR8s3mAZOJrP1gwyvAcIYl3GWtpX1"\n'
                      '        crossorigin="anonymous"></script>')
        if html.count(native_tag) != 1:
            raise RuntimeError('Graphify HTML script template changed; inspect offline export before continuing.')
        (out / 'assets').mkdir(exist_ok=True)
        (out / 'assets/vis-network.min.js').write_bytes(asset)
        (out / 'graph.html').write_text(html.replace(native_tag, '<script src="assets/vis-network.min.js"></script>'), encoding='utf-8')
        cohesion = score_all(graph, communities)
        gods = god_nodes(graph)
        surprises = surprising_connections(graph, communities)
        report = generate(graph, communities, cohesion, labels, gods, surprises,
                          detection, {'input': 0, 'output': 0}, str(corpus))
        (out / 'GRAPH_REPORT.md').write_text(report, encoding='utf-8')
        write_json(out / 'graph-health.json', health)
        write_json(out / '.graphify_extract.json', extraction)
        write_json(out / '.graphify_analysis.json', dict(communities=communities, cohesion=cohesion, gods=gods, surprises=surprises, questions=[]))
        write_json(out / '.graphify_detect.json', detection)
        (out / '.graphify_root').write_text(str(corpus), encoding='utf-8')
        (out / '.graphify_python').write_text(sys.executable, encoding='utf-8')
        save_manifest(detection['files'], root=corpus, manifest_path=str(out / 'manifest.json'), scan_corpus=detection['files']['code'])
        print(json.dumps(dict(files=len(paths), nodes=graph.number_of_nodes(), edges=graph.number_of_edges(), model_tokens=0)))
    finally:
        with (folder / 'commands.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(), mode=mode, args=args, network_attempts=attempts)) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status').add_argument('--require-fresh', action='store_true')
    commands.add_parser('refresh').add_argument('--force', action='store_true')
    query = commands.add_parser('query')
    query.add_argument('terms'); query.add_argument('--budget', type=int, default=1800)
    commands.add_parser('explain').add_argument('node')
    path = commands.add_parser('path')
    path.add_argument('source'); path.add_argument('target')
    args = parser.parse_args(argv)
    layout = CodeMap()
    if args.command == 'status':
        state = layout.status()
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return int(args.require_fresh and not state['fresh'])
    with layout.locked():
        state = layout.refresh(force=args.command == 'refresh' and args.force)
        if args.command == 'refresh':
            print(json.dumps(state, ensure_ascii=False, indent=2))
        else:
            if args.command == 'query':
                command = ['query', args.terms, '--budget', str(args.budget)]
            elif args.command == 'path':
                command = ['path', args.source, args.target]
            else:
                command = ['explain', args.node]
            print(layout.child('_cli', *command), end='')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        if len(sys.argv) > 2 and sys.argv[1] in ('_build', '_cli'):
            isolated_main(sys.argv[1], sys.argv[2], sys.argv[3:])
        else:
            sys.exit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f'Graphify workflow failed: {error}', file=sys.stderr)
        sys.exit(2)
