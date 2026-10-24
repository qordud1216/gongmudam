"""Start a protected Cloudflare Quick Tunnel to the existing loopback-only app.
No unauthenticated tunnel path is provided. Configuration/logs stay under data/.
"""
from __future__ import annotations
import argparse,json,os,re,shutil,subprocess,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'data'/'external-access'
EMAIL=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._%+\-]{0,63}@(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$')
PUBLIC=re.compile(r'https://([a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com)(?![a-z0-9.\-])')
def now():return datetime.now(timezone.utc).isoformat()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
def read(path):return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
def emails(values):
    if not values:raise ValueError('허용 이메일이 없습니다. --allow-email 이메일주소를 지정하세요.')
    result=[]
    for value in values:
        value=value.strip().lower()
        if not EMAIL.fullmatch(value):raise ValueError('허용할 개인 이메일 주소를 정확히 입력하세요. 전체 허용·와일드카드는 지원하지 않습니다.')
        if value not in result:result.append(value)
    return result

def origin(port):
    if not isinstance(port,int) or isinstance(port,bool) or not 1024<=port<=65535:raise ValueError('유효한 로컬 포트를 지정하세요.')
    return f'http://127.0.0.1:{port}'
def app_ready(url):
    try:
        with urlopen(url+'/openapi.json',timeout=5) as r:doc=json.load(r)
        return doc.get('info',{}).get('title')=='서무비서' and '/api/folders/change-inbox' in doc.get('paths',{})
    except Exception:return False

def cloudflared():
    found=shutil.which('cloudflared')
    if not found:
        candidate=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'cloudflared'/'cloudflared.exe'
        if candidate.is_file():found=str(candidate)
    if not found:raise ValueError('cloudflared를 찾지 못했습니다.')
    help_text=subprocess.check_output([found,'tunnel','--help'],encoding='utf-8',errors='replace',timeout=15)
    if '--allowed-mail' not in help_text:raise ValueError('설치된 cloudflared가 이메일 인증을 지원하지 않습니다. 인증 없이 공개하지 않습니다.')
    return str(Path(found).resolve())

def command(executable,url,allowed,log):
    allowed=emails(allowed)
    if not re.fullmatch(r'http://127\.0\.0\.1:\d{4,5}',url):raise ValueError('이 PC의 루프백 앱 주소만 연결할 수 있습니다.')
    args=[executable,'tunnel','--no-autoupdate','--url',url,'--metrics','127.0.0.1:0','--management-diagnostics=false','--loglevel','info','--logfile',str(log)]
    for email in allowed:args.extend(['--allowed-mail',email])
    return args

def tracked(state,private=None):
    """Check executable and unique launch log marker before touching an old PID."""
    if os.name!='nt' or not state:return False
    private=Path(private or PRIVATE).resolve()
    pid=state.get('pid');marker=Path(state.get('log','')).resolve()
    if not isinstance(pid,int) or isinstance(pid,bool) or pid<1 or not marker.is_relative_to(private):return False
    script=f'[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); Get-CimInstance Win32_Process -Filter "ProcessId={pid}" | Select-Object ExecutablePath,CommandLine | ConvertTo-Json -Compress'
    try:
        raw=subprocess.check_output(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],encoding='utf-8',errors='replace',timeout=10)
        p=json.loads(raw) if raw.strip() else {}
        return bool(p and os.path.normcase(p.get('ExecutablePath') or '')==os.path.normcase(state.get('executable','')) and str(marker).casefold() in (p.get('CommandLine') or '').casefold() and state.get('origin','') in (p.get('CommandLine') or ''))
    except (OSError,subprocess.SubprocessError,ValueError):return False

def public_url(state,private=None):
    private=Path(private or PRIVATE).resolve();values=[]
    for name in ('log','output_log'):
        if not state.get(name):continue
        p=Path(state[name]).resolve()
        if not p.is_relative_to(private):continue
        try:values.extend(m.group(0) for m in PUBLIC.finditer(p.read_text(encoding='utf-8',errors='replace')))
        except OSError:pass
    return next(iter(dict.fromkeys(values)),None)

def status():
    settings=read(PRIVATE/'settings.json');state=read(PRIVATE/'state.json');active=tracked(state)
    result={'running':active,'email_authentication_required':True,'allowed_email_count':len(settings.get('allowed_emails',[])),
            'origin':state.get('origin'),'url':public_url(state) if active else None,'pid':state.get('pid') if active else None,
            'started_at':state.get('started_at'),'temporary_hostname':True,'logs_directory':str(PRIVATE)}
    if result['url']:
        state['public_url']=result['url'];write(PRIVATE/'state.json',state)
    return result

def start(values=None,port=None):
    if os.name!='nt':raise ValueError('이 실행 도구는 현재 Windows PC용입니다.')
    settings=read(PRIVATE/'settings.json');allowed=emails(values if values is not None else settings.get('allowed_emails',[]));url=origin(port if port is not None else settings.get('port',8766))
    previous=read(PRIVATE/'state.json')
    if tracked(previous):raise ValueError('이미 이 도구의 터널이 실행 중입니다. 허용 목록을 바꾸려면 먼저 --stop으로 종료하세요.')
    executable=cloudflared()
    if not app_ready(url):raise ValueError('해당 포트의 서무비서 앱을 먼저 실행하세요. 다른 프로그램은 외부로 연결하지 않습니다.')
    PRIVATE.mkdir(parents=True,exist_ok=True);launch=uuid.uuid4().hex;log=PRIVATE/(launch+'.log');output=PRIVATE/(launch+'.output.log')
    args=command(executable,url,allowed,log)
    write(PRIVATE/'settings.json',dict(allowed_emails=allowed,port=int(url.rsplit(':',1)[1]),authentication='cloudflare-quick-tunnel-email-pin'))
    with output.open('wb') as stream:
        process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    write(PRIVATE/'state.json',dict(pid=process.pid,executable=executable,origin=url,log=str(log),output_log=str(output),started_at=now(),authentication='cloudflare-quick-tunnel-email-pin',allowed_email_count=len(allowed)))
    return {'started':True,'pid':process.pid,'email_authentication_required':True,'allowed_email_count':len(allowed),'message':'보호된 주소를 준비 중입니다. --status로 연결 주소를 확인하세요.'}

def stop(private=None):
    private=Path(private or PRIVATE)
    state=read(private/'state.json')
    if not tracked(state,private):return {'stopped':False,'message':'이 도구가 시작한 활성 터널이 없습니다. 다른 프로세스는 종료하지 않았습니다.'}
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',f"Stop-Process -Id {int(state['pid'])} -ErrorAction Stop"],check=True,timeout=10)
    state.update(stopped_at=now(),public_url=None);write(private/'state.json',state)
    return {'stopped':True,'message':'외부 접속을 종료했습니다. 로컬 서무비서와 AI는 계속 실행됩니다.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--start',action='store_true');mode.add_argument('--status',action='store_true');mode.add_argument('--stop',action='store_true')
    parser.add_argument('--allow-email',action='append');parser.add_argument('--port',type=int)
    args=parser.parse_args()
    if (args.allow_email is not None or args.port is not None) and not args.start:parser.error('허용 이메일·포트 지정은 --start에서만 사용합니다.')
    try:result=start(args.allow_email,args.port) if args.start else stop() if args.stop else status()
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False));return 1
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
