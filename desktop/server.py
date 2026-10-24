"""Standalone B desktop preview and read-only official agency lookup."""
import argparse
import json
import sqlite3
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from agency_directory import AgencyDirectory

ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    directory_store: AgencyDirectory

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        path = unquote(url.path)
        if path.startswith('/api/'):
            try:
                if path == '/api/health':
                    return self.send_json({'status': 'ok', 'source': self.directory_store.source})
                if path == '/api/agencies':
                    query = parse_qs(url.query)
                    return self.send_json(self.directory_store.search(query.get('q', [''])[0],
                        int(query.get('page', ['1'])[0]), int(query.get('limit', ['8'])[0])))
                if path.startswith('/api/agencies/'):
                    return self.send_json(self.directory_store.detail(path[len('/api/agencies/'):]))
                return self.send_json({'error': '요청한 조회 기능이 없습니다.'}, 404)
            except ValueError as error:
                return self.send_json({'error': str(error)}, 400)
            except KeyError:
                return self.send_json({'error': '기관코드를 찾지 못했습니다.'}, 404)
            except sqlite3.Error:
                return self.send_json({'error': '기관 검색 자료를 읽지 못했습니다. 잠시 후 다시 시도해 주세요.'}, 503)
        # Never serve databases, Python code, private source files, or directory listings.
        candidate = (ROOT / path.lstrip('/')).resolve()
        if path == '/':
            self.path = '/index.html' + ('?' + url.query if url.query else '')
        elif not candidate.is_relative_to(ROOT) or not candidate.is_file() or not (
            candidate.parent == ROOT and candidate.suffix in ('.html', '.css', '.js') or
            candidate.is_relative_to(ROOT / 'assets')):
            return self.send_error(404)
        return super().do_GET()

    def list_directory(self, path):
        return self.send_error(404)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8891)
    parser.add_argument('--database', type=Path, default=ROOT / 'data' / 'agencies-v1.sqlite')
    args = parser.parse_args()
    Handler.directory_store = AgencyDirectory(args.database)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, directory=str(ROOT)))
    print(f'Seomu desktop: http://127.0.0.1:{args.port}/ | agency snapshot {Handler.directory_store.source.get("sourceUpdatedAt")}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
