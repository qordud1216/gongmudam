"""Verify model status in an isolated app, with two real local models and a labelled HTTP fixture."""
from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
import httpx


def run(base, output):
    url=urlsplit(base)
    if url.hostname!='127.0.0.1' or url.scheme!='http' or url.port in (8766,8767) or url.path not in ('','/'):
        raise ValueError('Use a separate loopback installation, never the live/private demo')
    report=dict(base=base,synthetic_only=True,real_models=[],checks=[])
    client=httpx.Client(base_url=base,timeout=75)
    def request(method,path,body=None,status=200):
        response=client.request(method,path,json=body)
        assert response.status_code==status,(method,path,response.status_code,response.text[:100])
        return response.json()
    original=request('GET','/api/settings')['llm']['active']
    def select(name,values=None):
        request('PUT','/api/settings/llm',dict(profile=name,active=name,values=values))
        return request('GET','/api/workspace/model-status')
    def check(snapshot):return request('POST','/api/workspace/model-check',dict(selection_id=snapshot['selection_id']))
    def record(name,**details):report['checks'].append(dict(name=name,passed=True,**details))
    fixture=dict(mode='ready',get=0,post=0,model='fixture-v48',entered=threading.Event(),release=threading.Event())
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,body):
            raw=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            fixture['get']+=1
            if self.path!='/judge/v1/models':return self.reply(404,{})
            if self.headers.get('Authorization')!='Bearer fixture-only-token':return self.reply(401,{})
            if fixture['mode']=='unsupported':return self.reply(404,{})
            return self.reply(200,dict(data=[dict(id=fixture['model'])]))
        def do_POST(self):
            fixture['post']+=1
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert body['model']==fixture['model']
            assert body['messages']==[dict(role='user',content='Return only this JSON object: {"ok": true}')]
            if self.headers.get('Authorization')!='Bearer fixture-only-token':return self.reply(401,{})
            if fixture['mode']=='delayed':fixture['entered'].set();fixture['release'].wait(15)
            model='different-fixture' if fixture['mode']=='wrong' else fixture['model']
            return self.reply(200,dict(model=model,choices=[dict(message=dict(content='{"ok":true}'))]))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        # These are real installed Ollama models; no application document enters the request.
        for name,model in [('local_gemma','gemma3:4b'),('local_llama','llama3.2:3b')]:
            selected=select(name)
            assert selected['model']==model and selected['connection']['state']=='ready'
            assert selected['response']['state']=='unverified'
            value=check(selected)
            assert value['response']['state']=='verified',value
            assert value['response']['requested_model']==model and value['response']['response_model']==model
            assert request('GET','/api/workspace/model-status')['response']['state']=='verified'
            report['real_models'].append(dict(profile=name,model=model,**value['response']))
        record('Gemma and Llama actual responses and server-reported identities verified',real_inference=True)
        back=select('local_gemma')
        assert back['response']['state']=='unverified'
        record('switching back does not reuse an earlier verified result')
        offline=select('offline');assert offline['connection']['state']=='offline'
        request('POST','/api/workspace/model-check',dict(selection_id=offline['selection_id']),422)
        missing=select('status-v48-missing',dict(provider='openai_compatible',base_url='http://127.0.0.1:11434/v1',model='seomu-v48-not-installed'))
        assert missing['connection']['state']=='model_missing'
        down=select('status-v48-unavailable',dict(provider='openai_compatible',base_url='http://127.0.0.1:1/v1',model='gemma3:4b',timeout=2))
        assert down['connection']['state']=='unreachable'
        external=select('status-v48-external',dict(provider='openai_compatible',base_url='https://example.invalid/v1',model='external-example'))
        assert external['connection']['state']=='external'
        record('offline, missing model, closed local server and external profile are distinct')
        settings=dict(provider='openai_compatible',base_url=f'http://127.0.0.1:{server.server_port}/judge/v1',model=fixture['model'],api_key='fixture-only-token',timeout=30)
        selected=select('status-v48-fixture',settings)
        assert selected['connection']['state']=='ready'
        assert check(selected)['response']['state']=='verified'
        assert fixture['get']>0 and fixture['post']>0
        assert 'fixture-only-token' not in json.dumps(selected)
        record('different local engine port/path and authenticated discovery use selected endpoint',http_fixture=True)
        fixture['mode']='wrong'
        assert check(selected)['response']['state']=='model_mismatch'
        fixture['mode']='unsupported'
        selected=request('GET','/api/workspace/model-status');assert selected['connection']['state']=='unsupported'
        assert check(selected)['response']['state']=='verified'
        record('HTTP fixture model mismatch is rejected; explicit test works without models listing',http_fixture=True)
        fixture['mode']='delayed'
        selected=request('GET','/api/workspace/model-status')
        late=[]
        def old_check():
            response=client.post('/api/workspace/model-check',json=dict(selection_id=selected['selection_id']))
            late.append(dict(status=response.status_code,body=response.json()))
        waiting=threading.Thread(target=old_check);waiting.start()
        try:
            assert fixture['entered'].wait(10)
            value=request('GET','/api/workspace/model-status');assert value['response']['state']=='checking'
            request('POST','/api/workspace/model-check',dict(selection_id=selected['selection_id']),409)
            current=select('local_llama');assert current['response']['state']=='unverified' and current['check_in_progress']
        finally:
            fixture['release'].set();waiting.join(20)
        assert late[0]['status']==409 and late[0]['body']['detail']['code']=='selection_changed'
        assert request('GET','/api/workspace/model-status')['response']['state']=='unverified'
        record('actual delayed HTTP reply cannot publish after switch; concurrent test is rejected',http_fixture=True)
        report['passed']=True
    finally:
        request('PUT','/api/settings/llm',dict(active=original))
        report['restored_profile']=original
        server.shutdown();server.server_close();client.close()
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--base',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    result=run(args.base,args.output)
    print(json.dumps(dict(passed=result.get('passed',False),real_models=result['real_models'],checks=len(result['checks'])),ensure_ascii=False))
