"""Manual one-click Windows launcher for the existing PC-backed Gongmudam site."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import socket
import subprocess
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.local-runtime/launcher'
PUBLIC_URL = 'https://gongmudam.visanu81.workers.dev'
LOCAL_URL = 'http://127.0.0.1:8892'
TUNNEL_ID = 'fcf40f16-2c0e-4541-b529-77d357f1be1a'
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
GROUP = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)


class LaunchError(RuntimeError):
    pass


class AlreadyLaunching(LaunchError):
    pass


def ready(value):
    return isinstance(value, dict) and all(value.get(k) is True for k in
        ('desktop_connected', 'public_demo', 'private_data_isolated', 'requires_origin_pc')) and value.get('status') == 'ok'


def probe(base):
    # Reuse the application's HTTPS client and CA bundle. urllib's default
    # client is rejected by the public edge even when the same API is healthy.
    import httpx
    try:
        response = httpx.get(base + '/api/gongmudam/status', timeout=4,
            headers={'Accept': 'application/json', 'Cache-Control': 'no-cache'}, follow_redirects=False)
        return response.status_code == 200 and len(response.content) <= 65536 and ready(response.json())
    except (OSError, httpx.HTTPError, ValueError):
        return False


def port_in_use():
    with socket.socket() as connection:
        connection.settimeout(1)
        return connection.connect_ex(('127.0.0.1', 8892)) == 0


class LaunchLock:
    """A per-checkout Windows mutex prevents concurrent double-click starts."""
    def __enter__(self):
        if os.name != 'nt':
            raise LaunchError('이 실행 버튼은 Windows PC용입니다.')
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        name = 'Local\\GongmudamLauncher_' + hashlib.sha256(str(ROOT).casefold().encode()).hexdigest()[:24]
        self.handle = self.kernel.CreateMutexW(None, False, name)
        if not self.handle:
            raise LaunchError('실행 잠금을 만들지 못했습니다.')
        if ctypes.get_last_error() == 183:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise AlreadyLaunching('공무담을 준비하는 창이 이미 있습니다. 잠시 기다려 주세요.')
        return self

    def __exit__(self, *_):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def tunnel_processes():
    """Return only own tunnel wrapper PIDs; never return raw process arguments."""
    script = ("[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
              "$items=@(Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" -ErrorAction Stop | "
              "Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains('wrangler') "
              f"-and $_.CommandLine.Contains('{TUNNEL_ID}') "
              "-and $_.CommandLine -match 'tunnel\\s+run' } | ForEach-Object { [int]$_.ProcessId }); "
              "ConvertTo-Json -InputObject $items -Compress")
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
            check=True, capture_output=True, encoding='utf-8', timeout=15, creationflags=HIDDEN)
        data = json.loads(result.stdout.strip() or '[]')
        return [p for p in data if type(p) is int and p > 0]
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise LaunchError('터널 실행 상태를 확인하지 못했습니다. 로그를 확인한 뒤 다시 실행해 주세요.') from error


def write_state(value):
    STATE.mkdir(parents=True, exist_ok=True)
    target = STATE / 'startup-state.json'
    temp = STATE / ('startup-state.' + str(os.getpid()) + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, target)


def open_public(result):
    try:
        opened = bool(webbrowser.open(PUBLIC_URL))
    except (OSError, webbrowser.Error):
        opened = False
    result['browser_opened'] = opened
    write_state(result)
    return opened


class Launcher:
    def __init__(self, notify=lambda _: None):
        self.notify = notify
        self.result = {'status': 'starting', 'public_url': PUBLIC_URL,
                       'server_started': False, 'tunnel_started': False,
                       'checked_at': datetime.now(timezone.utc).isoformat()}
        self.children = []

    def spawn(self, args, name, env=None):
        STATE.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        log = STATE / f'{name}-{stamp}.log'
        with log.open('wb') as stream:
            process = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT, creationflags=HIDDEN | GROUP)
        self.children.append(process)
        self.result[name + '_pid'] = process.pid
        self.result[name + '_log'] = str(log)
        write_state(self.result)
        return process

    def wait_ready(self, url, seconds, process=None):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if probe(url):
                return True
            if process is not None and process.poll() is not None:
                return False
            time.sleep(0.7)
        return False

    def ensure_server(self):
        self.notify('공무담 서버를 확인하고 있습니다…')
        if probe(LOCAL_URL):
            self.notify('이미 켜진 공무담 서버를 사용합니다.')
            return
        if port_in_use():
            if self.wait_ready(LOCAL_URL, 20):
                return
            raise LaunchError('8892 포트가 사용 중이지만 공무담 서버를 확인하지 못했습니다. 다른 프로그램을 임의로 종료하지 않았습니다.')
        python = ROOT / 'service/.venv/Scripts/python.exe'
        if not python.is_file():
            raise LaunchError('처음 설치가 필요합니다. 프로젝트의 install-service.bat을 먼저 실행해 주세요.')
        self.notify('저장된 업무를 유지하며 서버를 시작합니다…')
        STATE.mkdir(parents=True, exist_ok=True)
        with (STATE / 'prepare.log').open('wb') as stream:
            setup = subprocess.run([str(python), str(ROOT / 'tools/prepare_public_runtime.py')],
                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=120, creationflags=HIDDEN)
        if setup.returncode:
            raise LaunchError('업무 실행본 준비에 실패했습니다. 로그 폴더의 prepare.log를 확인해 주세요. 기존 업무는 덮어쓰지 않았습니다.')
        env = os.environ.copy()
        env.update(GONGMUDAM_SERVICE_ROOT=str(ROOT / '.local-runtime/service'), GONGMUDAM_PUBLIC='1')
        process = self.spawn([str(python), '-m', 'uvicorn', 'integration.application:create_app', '--factory',
            '--host', '127.0.0.1', '--port', '8892'], 'server', env)
        self.result['server_started'] = True
        if not self.wait_ready(LOCAL_URL, 45, process):
            raise LaunchError('공무담 서버가 준비되지 않았습니다. 서버 로그를 확인해 주세요.')

    def ensure_tunnel(self):
        self.notify('고정 주소 연결을 확인하고 있습니다…')
        if probe(PUBLIC_URL):
            self.notify('이미 연결된 Cloudflare 터널을 사용합니다.')
            return
        existing = tunnel_processes()
        process = None
        if existing:
            self.result['tunnel_existing_pids'] = existing
            self.notify('실행 중인 Cloudflare 터널의 연결을 기다립니다…')
        else:
            script = ROOT / 'node_modules/wrangler/bin/wrangler.js'
            node = shutil.which('node')
            fallback = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'nodejs/node.exe'
            if not node and fallback.is_file():
                node = str(fallback)
            if not node or not script.is_file():
                raise LaunchError('터널 도구가 없습니다. Node.js 설치와 프로젝트의 npm ci 실행을 확인해 주세요.')
            self.notify('Cloudflare 터널을 시작합니다…')
            process = self.spawn([node, str(script), 'tunnel', 'run', TUNNEL_ID, '--log-level', 'info'], 'tunnel')
            self.result['tunnel_started'] = True
        if not self.wait_ready(PUBLIC_URL, 75, process):
            raise LaunchError('외부 주소 연결이 확인되지 않았습니다. 인터넷과 터널 로그를 확인해 주세요. Cloudflare 로그인이 만료됐으면 run-tunnel.bat에서 안내를 확인해 주세요.')

    def run(self):
        try:
            self.ensure_server()
            self.ensure_tunnel()
            self.result.update(status='ready', checked_at=datetime.now(timezone.utc).isoformat())
            write_state(self.result)
            self.notify('연결 완료. 같은 공무담 주소를 사용할 수 있습니다.')
            return self.result
        except Exception as error:
            self.result.update(status='error', message=str(error))
            write_state(self.result)
            raise


def gui(open_browser=True):
    import tkinter as tk
    from tkinter import ttk
    window = tk.Tk()
    window.title('공무담 실행')
    window.geometry('540x235')
    window.resizable(False, False)
    icon = STATE / 'gongmudam.ico'
    if icon.is_file():
        try:
            window.iconbitmap(str(icon))
        except tk.TclError:
            pass
    frame = ttk.Frame(window, padding=22)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='공무담을 준비합니다', font=('맑은 고딕', 16, 'bold')).pack(anchor='w')
    status = tk.StringVar(value='서버와 고정 주소를 확인하고 있습니다…')
    ttk.Label(frame, textvariable=status, wraplength=490).pack(anchor='w', pady=(14, 12))
    bar = ttk.Progressbar(frame, mode='indeterminate')
    bar.pack(fill='x'); bar.start(12)
    ttk.Label(frame, text='PC의 앱·터널이 실행되는 동안 같은 주소로 접속합니다.', wraplength=490).pack(anchor='w', pady=(10, 10))
    buttons = ttk.Frame(frame); buttons.pack(fill='x')
    visit = ttk.Button(buttons, text='공무담 열기', command=lambda: webbrowser.open(PUBLIC_URL))
    visit.pack(side='left'); visit.state(['disabled'])
    ttk.Button(buttons, text='로그 폴더', command=lambda: os.startfile(str(STATE))).pack(side='left', padx=8)
    close = ttk.Button(buttons, text='닫기', command=window.destroy)
    close.pack(side='right'); close.state(['disabled'])
    messages = queue.Queue()
    busy = True

    def work():
        try:
            with LaunchLock():
                result = Launcher(lambda message: messages.put(('progress', message))).run()
            messages.put(('ready', result))
        except AlreadyLaunching as error:
            messages.put(('duplicate', str(error)))
        except Exception as error:
            messages.put(('error', str(error)))

    def poll():
        nonlocal busy
        try:
            while True:
                kind, value = messages.get_nowait()
                if kind == 'progress':
                    status.set(value); continue
                busy = False; bar.stop(); close.state(['!disabled'])
                if kind == 'ready':
                    status.set('연결 완료. 창을 닫아도 서버와 터널은 계속 실행됩니다.')
                    visit.state(['!disabled'])
                    if open_browser:
                        if open_public(value):
                            window.after(2500, window.destroy)
                        else:
                            status.set('서버 연결은 완료됐지만 브라우저를 열지 못했습니다. 공무담 열기 버튼을 눌러 주세요.')
                else:
                    status.set(value)
        except queue.Empty:
            pass
        if window.winfo_exists():
            window.after(100, poll)

    window.protocol('WM_DELETE_WINDOW', lambda: window.iconify() if busy else window.destroy())
    STATE.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=work, daemon=True).start()
    window.after(100, poll)
    window.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--status-only', action='store_true')
    args = parser.parse_args()
    if args.status_only:
        print(json.dumps({'local_ready': probe(LOCAL_URL), 'public_ready': probe(PUBLIC_URL)}))
        return 0
    if not args.headless:
        gui(not args.no_browser)
        return 0
    try:
        with LaunchLock():
            result = Launcher().run()
        if not args.no_browser:
            open_public(result)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except AlreadyLaunching as error:
        print(json.dumps({'status': 'already_launching', 'message': str(error)}, ensure_ascii=True))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'error', 'message': str(error)}, ensure_ascii=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
