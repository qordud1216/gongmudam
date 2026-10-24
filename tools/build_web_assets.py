"""Build an explicit frontend-only asset set; never include databases or source."""
from pathlib import Path
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]


def build():
    source = ROOT / 'desktop'
    output = ROOT / '.wrangler/web-assets'
    output.mkdir(parents=True, exist_ok=True)
    wanted = {p.relative_to(source).as_posix(): p for p in source.iterdir()
              if p.is_file() and p.suffix in {'.html', '.css', '.js'}}
    for path in (source / 'assets').rglob('*'):
        if path.is_file() and path.suffix in {'.svg', '.png', '.woff2', '.txt'}:
            wanted[path.relative_to(source).as_posix()] = path
    # Only delete stale generated files within this exact output folder.
    for path in output.rglob('*'):
        if path.is_file() and path.relative_to(output).as_posix() not in {'desktop/' + n for n in wanted}:
            path.unlink()
    for name, path in wanted.items():
        dest = output / 'desktop' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    print(json.dumps({'frontend_assets': len(wanted), 'database_uploaded': False}))


if __name__ == '__main__':
    build()
