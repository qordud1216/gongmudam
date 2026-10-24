"""출장 데모 진입점. 기존 앱과 같은 서버를 별도 포트에서 연다."""
import threading
import webbrowser
import argparse

import uvicorn

from .main import app


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description='서무비서 통합 업무 시작')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    if not 1<=args.port<=65535: parser.error('포트는 1~65535 사이여야 합니다.')
    address = f"http://127.0.0.1:{args.port}/start.html"
    print(f"서무비서 통합 시작: {address}  (종료: Ctrl+C)")
    if not args.no_browser:
        timer = threading.Timer(2, lambda: webbrowser.open(address))
        timer.daemon = True
        timer.start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
