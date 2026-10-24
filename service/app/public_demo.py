"""Factory for a separate, intentionally public synthetic-demo installation only.
The private app never imports this module. A build marker is mandatory.
"""
from __future__ import annotations
import asyncio,copy,json,re,time,os,threading
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import HTTPException,Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,Field

ROOT=Path(__file__).resolve().parents[1]
MODELS={'local_gemma':'gemma3:4b','local_llama':'llama3.2:3b'}

def validate_config(cfg,baseline):
    candidate=copy.deepcopy(cfg);original=copy.deepcopy(baseline)
    active=candidate.get('llm',{}).get('active')
    if active not in MODELS:raise ValueError('공개 시연에서는 준비한 Gemma·Llama만 선택할 수 있습니다.')
    candidate['llm']['active']=original['llm']['active']
    if candidate!=original:raise ValueError('공개 시연에서는 서버 주소·키·모델 설정을 변경할 수 없습니다.')

def restricted_roots(values,base,original):
    allowed=base.resolve(strict=True)
    if any(not Path(os.path.abspath(value)).is_relative_to(allowed) for value in values):raise HTTPException(403,'공개 시연은 제공된 시연자료 폴더만 연결할 수 있습니다.')
    roots=original(values)
    if any(not root.is_relative_to(allowed) for root in roots):raise HTTPException(403,'공개 시연은 제공된 시연자료 폴더만 연결할 수 있습니다. 실제 PC 폴더는 연결하지 않습니다.')
    return roots

def safe_name(value):
    if not re.fullmatch(r'[가-힣A-Za-z0-9_() .-]{1,100}\.txt',value) or '..' in value or value.startswith('.') or value.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:
        raise ValueError('한글·영문·숫자 이름의 TXT 파일만 추가할 수 있습니다.')
    return '공개_'+value

class NewFile(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=5,max_length=104)
    content:str=Field(min_length=10,max_length=12000)

def create_app():
    marker=ROOT/'public-demo.json'
    if not marker.is_file():raise RuntimeError('별도 공개 시연 복사본에서만 실행할 수 있습니다. 원본 앱은 공개 모드로 실행하지 않습니다.')
    definition=json.loads(marker.read_text(encoding='utf-8'))
    if definition.get('private_data_isolated') is not True:raise RuntimeError('공개 시연 데이터 분리 표식이 없습니다.')
    sandbox=ROOT/'synthetic-folders';sandbox.mkdir(exist_ok=True);incoming=sandbox/'추가회신';incoming.mkdir(exist_ok=True)
    from . import config,folders
    baseline=config.load()
    if set(baseline.get('llm',{}).get('profiles',{}))!=set(MODELS):raise RuntimeError('공개 시연 모델 구성이 잘못됐습니다.')
    for key,model in MODELS.items():
        p=baseline['llm']['profiles'][key]
        if p.get('provider')!='openai_compatible' or p.get('base_url')!='http://127.0.0.1:11434/v1' or p.get('model')!=model or p.get('api_key') or p.get('api_key_env'):raise RuntimeError('공개 시연은 고정된 로컬 AI만 사용합니다.')
    original_save=config.save;original_roots=folders.roots_checked
    def checked_save(value):validate_config(value,baseline);return original_save(value)
    def checked_roots(values):return restricted_roots(values,sandbox,original_roots)
    config.save=checked_save;folders.roots_checked=checked_roots
    from . import folder_ai,llm
    native_calls=deque();native_lock=threading.Lock();original_call=folder_ai.call_model
    def limited_model(*args,**kwargs):
        with native_lock:
            current=time.monotonic()
            while native_calls and current-native_calls[0]>3600:native_calls.popleft()
            if len(native_calls)>=30:raise llm.LLMError('공개 시연 AI의 시간당 요청 한도입니다. 잠시 후 다시 시도하세요.')
            native_calls.append(current)
        return original_call(*args,**kwargs)
    folder_ai.call_model=limited_model
    from .main import app
    app.state.public_demo=True
    static_mount=app.router.routes.pop()
    if getattr(static_mount,'path',None)!='':raise RuntimeError('정적 파일 라우트 위치를 확인하세요.')
    semaphore=asyncio.Semaphore(1);model_calls=deque();writes=deque()
    @app.middleware('http')
    async def public_limits(request:Request,call_next):
        path=request.url.path.rstrip('/');method=request.method
        if method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            if origin and urlsplit(origin).netloc!=request.headers.get('host'):return JSONResponse({'detail':'다른 사이트에서의 요청은 허용하지 않습니다.'},403)
            try:length=int(request.headers.get('content-length','0'))
            except ValueError:return JSONResponse({'detail':'요청 크기를 확인하세요.'},400)
            if length>12*1024*1024:return JSONResponse({'detail':'공개 시연의 업로드 한도는 12MB입니다.'},413)
            chunks=[];size=0
            async for chunk in request.stream():
                size+=len(chunk)
                if size>12*1024*1024:return JSONResponse({'detail':'공개 시연의 업로드 한도는 12MB입니다.'},413)
                chunks.append(chunk)
            request._body=b''.join(chunks)
            current=time.monotonic()
            while writes and current-writes[0]>60:writes.popleft()
            if len(writes)>=90:return JSONResponse({'detail':'공개 시연 요청이 많습니다. 잠시 후 다시 시도하세요.'},429,headers={'Retry-After':'60'})
            writes.append(current)
        is_model=method=='POST' and (path in ('/api/ask','/api/local-ai/run','/api/llm/test') or path.endswith('/prefill') or path.endswith('/ai-runs'))
        if is_model:
            current=time.monotonic()
            while model_calls and current-model_calls[0]>3600:model_calls.popleft()
            if len(model_calls)>=30 or semaphore.locked():return JSONResponse({'detail':'공유 로컬 AI가 사용 중이거나 시연 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.'},429,headers={'Retry-After':'60'})
            await semaphore.acquire();model_calls.append(current)
        try:response=await call_next(request)
        finally:
            if is_model:semaphore.release()
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
        return response
    @app.get('/api/public-demo/status')
    def status():return dict(mode='public-synthetic-demo',private_data_isolated=True,pc_root_access=False,authentication=False,incoming_folder=str(incoming),folder_library_id=definition['folder_library_id'],models=MODELS,notice='누구나 같은 시연자료를 조회·수정할 수 있습니다. 실제 개인정보·업무자료를 입력하지 마세요.')
    @app.post('/api/public-demo/files',status_code=201)
    def add_file(body:NewFile):
        try:name=safe_name(body.name)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        path=incoming/name
        if path.is_symlink() or path.is_junction():raise HTTPException(403,'연결점 파일은 변경하지 않습니다.')
        with path.open('w',encoding='utf-8',newline='\n') as stream:stream.write(body.content)
        return dict(name=name,notice='공개 시연 폴더에 저장했습니다. 자동 감지 후 AI 변경 제안을 확인하세요.',library_id=definition['folder_library_id'])
    app.router.routes.append(static_mount)
    return app
