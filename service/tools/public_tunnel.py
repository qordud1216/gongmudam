"""Anonymous sharing is restricted to the separately built synthetic demo on 8767."""
from pathlib import Path
import argparse,json,subprocess,sys,uuid
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import external_access as ext
PRIVATE=ext.ROOT/'data'/'public-external-access'
ORIGIN='http://127.0.0.1:8767'
def check_origin():
    try:
        with urlopen(ORIGIN+'/api/public-demo/status',timeout=5) as response:value=json.load(response)
        return value.get('mode')=='public-synthetic-demo' and value.get('private_data_isolated') is True and value.get('pc_root_access') is False
    except Exception:return False

def start():
    if ext.os.name!='nt':raise ValueError('Windows PC용 공개 시연 도구입니다.')
    if ext.tracked(ext.read(PRIVATE/'state.json'),PRIVATE):raise ValueError('이미 공개 시연 링크가 실행 중입니다.')
    if not check_origin():raise ValueError('별도 공개 시연 서버가 확인되지 않았습니다. 원본 앱을 익명으로 공개하지 않습니다.')
    executable=ext.cloudflared();PRIVATE.mkdir(parents=True,exist_ok=True);launch=uuid.uuid4().hex
    log=PRIVATE/(launch+'.log');output=PRIVATE/(launch+'.output.log')
    args=[executable,'tunnel','--no-autoupdate','--url',ORIGIN,'--metrics','127.0.0.1:0','--management-diagnostics=false','--loglevel','info','--logfile',str(log)]
    with output.open('wb') as stream:process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    ext.write(PRIVATE/'state.json',dict(pid=process.pid,executable=executable,origin=ORIGIN,log=str(log),output_log=str(output),started_at=ext.now(),mode='anonymous-public-synthetic-demo'))
    return dict(started=True,pid=process.pid,authentication=False,private_app_exposed=False,message='공개 시연 주소를 생성 중입니다. --status로 확인하세요.')
def status():
    state=ext.read(PRIVATE/'state.json');active=ext.tracked(state,PRIVATE)
    return dict(running=active,authentication=False,private_app_exposed=False,origin=ORIGIN,url=ext.public_url(state,PRIVATE) if active else None,pid=state.get('pid') if active else None,temporary_hostname=True,public_demo_origin_ready=check_origin())
def main():
    parser=argparse.ArgumentParser(description=__doc__);group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--start',action='store_true');group.add_argument('--status',action='store_true');group.add_argument('--stop',action='store_true');args=parser.parse_args()
    try:value=start() if args.start else ext.stop(PRIVATE) if args.stop else status()
    except (ValueError,OSError,subprocess.SubprocessError) as exc:print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False));return 1
    print(json.dumps(value,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
