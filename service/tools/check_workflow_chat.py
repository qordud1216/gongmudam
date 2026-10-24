"""Run the chat-edit flow against running apps using newly created synthetic jobs only."""
import argparse
import json
import urllib.request
import uuid
from pathlib import Path


def check(port):
    base = f'http://127.0.0.1:{port}'
    trace = []
    def req(method, path, body=None):
        request = urllib.request.Request(base + path, method=method,
            data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    settings = dict(title='[합성 검증 v37] 대화로 교육 진행표 수정', situation='교육 참석 희망자 취합',
        course='합성 AI 활용 교육', event_date='2026-11-06', deadline='2026-10-30', departments=['합성총무팀','합성행정팀'])
    job = req('POST', '/api/adhoc/jobs', settings)
    key = job['id']
    def read(): return req('GET', f'/api/adhoc/jobs/{key}')
    def ask(query, snapshot, request_id=None, **extra):
        fields = dict(query=query, workflow_request_id=request_id or str(uuid.uuid4()))
        if snapshot:
            fields.update(education_job_id=key, workflow_revision=snapshot['workflow']['revision'], workflow_data_version=snapshot['version'])
        result = req('POST', '/api/ask', fields | extra)
        assert result['mode'] == 'workflow_edit', result
        trace.append(result)
        return result['workflow_chat']
    query = '검토 다음에 부서장 확인 단계를 넣어줘'
    request_id = str(uuid.uuid4())
    w = ask(query, job, request_id)
    assert w['status'] == 'applied'
    current = read()
    target = current['workflow']['steps'][4]['id']
    assert current['workflow']['steps'][4]['title'] == '부서장 확인'
    assert current['version'] == job['version'] == 1
    assert ask(query, job, request_id)['replayed']
    assert read() == current
    assert ask('안내 다음에 개인정보 확인 단계를 넣어줘', job)['status'] == 'conflict'
    assert read() == current
    assert ask('부서장 확인 이름을 최종 확인으로 바꿔줘', current)['status'] == 'applied'
    current = read()
    assert current['workflow']['steps'][4]['id'] == target
    assert ask('최종 확인을 검토 앞으로 옮겨줘', current)['status'] == 'applied'
    current = read()
    assert current['workflow']['steps'][3]['id'] == target
    assert ask('최종 확인 설명을 "명단과 부서 회신을 대조해요"로 바꿔줘', current)['status'] == 'applied'
    current = read()
    command = dict(action='add', title='2차 검토', revision=current['workflow']['revision'], data_version=current['version'])
    current = req('PATCH', f'/api/adhoc/jobs/{key}/workflow', command)
    w = ask('검토 다음에 추가 확인 단계를 넣어줘', current)
    assert w['status'] == 'choose_step' and len(w['choices']) == 2
    assert read() == current
    anchor = next(s['id'] for s in current['workflow']['steps'] if s['title'] == '2차 검토')
    w = ask('검토 다음에 추가 확인 단계를 넣어줘', current, w['request_id'], workflow_selection={'anchor':anchor})
    assert w['status'] == 'applied'
    current = read()
    assert current['workflow']['steps'][-2]['id'] == anchor
    assert current['workflow']['steps'][-1]['title'] == '추가 확인'
    assert current['version'] == 1
    assert all(not s['completed_at'] for s in current['workflow']['steps'])
    assert all(h['detail'].get('source') == 'chat' for h in current['workflow']['history'] if h['revision'] != 5)
    ambiguous = ask(query, None)
    assert ambiguous['status'] == 'choose_job', ambiguous
    assert read() == current
    ordinary = req('POST', '/api/ask', dict(query='교육 참석 희망자 취합 업무를 만들어줘', education_job_id=key))
    assert ordinary['mode'] == 'education_workflow'
    assert read() == current
    return dict(port=port, job_id=key, data_version=current['version'], revision=current['workflow']['revision'],
        order=[s['title'] for s in current['workflow']['steps']], trace=trace, job=current)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ports', type=int, nargs='+', default=[8766,8767])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = [check(port) for port in args.ports]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([dict(port=r['port'], job_id=r['job_id'], revision=r['revision'], data_version=r['data_version']) for r in results], ensure_ascii=False))
