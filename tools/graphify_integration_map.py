"""Map only the integration overlay; never change the packaged service map."""
import argparse
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['refresh', 'status', 'query'])
    parser.add_argument('terms', nargs='?', default='')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('service_code_map', ROOT / 'service/tools/graphify_code_map.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SCOPES = {'desktop': '.js', 'integration': '.py', 'cloudflare': '.js', 'tests': '.py', 'tools': '.py'}
    runtime = os.environ.get('SEOMU_GRAPHIFY_PYTHON')
    asset = os.environ.get('SEOMU_GRAPHIFY_ASSET')
    if not runtime or not asset:
        raise RuntimeError('Set SEOMU_GRAPHIFY_PYTHON and SEOMU_GRAPHIFY_ASSET to the isolated Graphify installation.')
    layout = module.CodeMap(project=ROOT, workspace=ROOT.parent / 'work/gongmudam-integration-map', runtime=runtime, asset=asset)
    if args.command == 'status':
        state = layout.status()
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return int(not state['fresh'])
    with layout.locked():
        state = layout.refresh()
        if args.command == 'refresh':
            print(json.dumps(state, ensure_ascii=False, indent=2))
        else:
            print(layout.child('_cli', 'query', args.terms, '--budget', '1200'), end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
