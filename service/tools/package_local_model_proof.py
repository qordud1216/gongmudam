"""이미 실행한 실제 증거를 검증하고 제출용 보고서·ZIP으로 묶는다."""
import argparse
import hashlib
import json
import shutil
import zipfile
from datetime import datetime,timezone,timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
EVIDENCE=ROOT/'docs'/'local-ai-evidence'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    data=json.loads((EVIDENCE/'local-ai-evidence.json').read_text(encoding='utf-8'))
    assert data['passed'] and len(data['runs'])==6
    assert {r['response_model'] for r in data['runs']}=={'gemma3:4b','llama3.2:3b'}
    for run in data['runs']:
        snapshot={k:v for k,v in run.items() if k!='evidence_sha256'}
        assert hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()==run['evidence_sha256']
        assert run['response_model']==run['requested_model']
        assert run['model_calls'][0]['response']['usage']['completion_tokens']>0
    for p,digest in data['source_sha256'].items(): assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==digest
    tests=json.loads((EVIDENCE/'unit-test-result.json').read_text(encoding='utf-8'));assert tests['exit_code']==0
    testlog=(EVIDENCE/'unit-tests.log').read_text(encoding='utf-8');assert 'Ran 219 tests' in testlog and testlog.rstrip().endswith('OK')
    date=datetime.fromisoformat(data['created_at']).astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S KST')
    lines=['# 세션2 서무비서 · 로컬 AI 2종 실제 구동 검증', '',f'검증 시작: {date}', '',
           '**실제 로컬 모델 실행 6건 통과 · 동일 업무의 앱 결과 3쌍 일치 · 실제 연결 실패 대체 안내 통과 · 자동 테스트 219개 통과.**','',
           '이 문서는 실제 실행 후 저장된 요청·응답 JSON과 테스트 원본 로그를 근거로 작성했습니다. 화면 표시만 바꾸거나 모의 응답을 실제 모델 성공으로 세지 않았습니다.', '',
           '## 실행 환경','',f"- OS: {data['environment']['os']}",f"- Python: {data['environment']['python']}",f"- Ollama: {data['environment']['ollama_version']}",
           '- 로컬 모델 주소: http://127.0.0.1:11434/v1',
           '- 모델은 이미 설치된 Gemma·Llama를 사용했습니다. 로컬 API 키는 필요하지 않았고 요청 헤더·키는 증거에 기록하지 않았습니다.', '',
           '| 모델 | 양자화 | 파일 크기 | 다운로드 SHA-256 |','| --- | --- | --- | --- |']
    for model in data['environment']['installed_models']:
        lines.append(f"| {model['name']} | {model['details']['quantization_level']} | {model['size']:,} bytes | {model['digest']} |")
    lines+=['','## 동일 업무 실제 실행','',
            '| 모델 | 합성 업무 | 실제 응답 모델명 | 소요시간 | 판정 |','| --- | --- | --- | --- | --- |']
    for r in data['runs']: lines.append(f"| {r['profile']} | {r['scenario']['title']} | {r['response_model']} | {r['elapsed_seconds']}초 | 통과 |")
    lines+=['','두 모델 모두 후보 중 기대하는 절차 카드를 실제로 선택했습니다. 카드 ID를 미리 고정해서 요청하지 않았습니다. 실제 응답 원문·모델명·토큰 사용량·처리시간은 각 JSON의 `model_calls`에서 확인할 수 있습니다.',
            '', '각 업무의 절차·서식·근거·기한을 포함한 전체 `plan`이 두 모델 사이에서 동일했습니다. 연가 사례에는 등록된 서식이 없어 서식 검사는 해당 없음입니다. 각 처리시간은 단일 측정이며 캐시·실행 순서·PC 부하가 달라 속도 순위로 해석하지 않습니다.', '',
            '## 잘못된 모델 인용·보충 설명 처리','',
            'LLM은 업무·근거 후보 선택을 보조합니다. 본문·기한은 앱이 등록자료로 구성합니다. 모델의 자유 생성 문장을 검증 없이 정답으로 사용하지 않습니다.','',
            '| 모델·업무 | 실제 관찰 내용 |','| --- | --- |']
    for r in data['runs']: lines.append(f"| {r['profile']} · {r['scenario_id']} | {r['result']['notice'] or '잘못된 근거 ID 제외 알림 없음'} / AI 보충 설명: {'있음' if r['result']['ai_note'] else '필터링 후 없음'} |")
    lines+=['','일부 실행에서 모델이 틀린 근거 ID를 반환했으며 앱이 이를 제외했습니다. 보충 설명은 기존 문장 필터에 의해 6건 모두 비어 있었습니다. 따라서 이 검증을 생성 문장의 정확도 100%나 모든 업무 성공률로 표현하면 안 됩니다.', '',
            '## 장애 대응·브라우저 재현','',
            f"- 실제 닫힌 포트 `127.0.0.1:1` 연결 실패 → `fallback` 안내 확인: {data['failure_check']['passed']}, {data['failure_check']['elapsed_seconds']}초.",
            '- 장애 대체 안내는 로컬 모델 실제 성공 6건에 포함하지 않았습니다.',
            '- 브라우저에서 Llama 출장 사례를 추가 실행했고 실제 응답과 결과를 `browser_llama_travel.json`에 보존했습니다. 이 추가 실행은 위 6건 표에 포함하지 않았습니다. 화면의 시간은 이 추가 실행으로 갱신될 수 있습니다.',
            '- `local-ai-models.png`는 저장된 결과와 브라우저 재실행 결과가 함께 보이는 화면입니다. 합성자료이며 기관 승인·실제 여비 지급을 수행하지 않았습니다.', '',
            '## 심사위원 재현 순서','',
            '1. 제출 소스 프로젝트에서 `run-travel.bat` 실행.',
            '2. Ollama에서 `gemma3:4b`, `llama3.2:3b` 설치·서버 실행 상태 확인.',
            '3. 앱 왼쪽 **로컬 AI · 2종 검증** 열기.',
            '4. 합성 업무를 고른 뒤 **같은 업무로 Gemma → Llama 비교** 실행. 실제 모델명·카드·서식·근거 확인.',
            '5. **서버 연결 실패 시 안내 확인** 실행. `fallback` 모드 확인.',
            '6. 일반 서무 화면에서는 **설정 · 모델 연결**에서 `local_gemma`·`local_llama`의 **이 모델 사용**을 선택해 기본 모델 교체.',
            '7. 프로젝트에서 `.venv/Scripts/python tools/verify_local_models.py`를 실행하면 원본 검증 기록 재생성.', '',
            '## 제출 묶음 구성','',
            '- 이 검증 보고서와 로컬 연결·교체·재현 안내서',
            '- 6건의 모델별 JSON + 통합 JSON + 브라우저 추가 실행 JSON',
            '- 실제 자동 시험 로그와 종료 코드 기록',
            '- 로컬 프로필 설정 예시, 재현 스크립트, 화면 캡처',
            '- 파일별 SHA-256 목록(목록 자체는 자기 참조를 피하기 위해 제외)', '',
            '이 ZIP은 증거 묶음입니다. 전체 소스·실행 방법은 별도 프로젝트 산출물과 함께 제출하고 모델 가중치는 포함하지 않습니다. 실제 규정 여비 계산의 법령 검증과 이 합성 서무업무 LLM 검증은 구분합니다.']
    report='\n'.join(lines)+'\n'
    report_name='세션2_로컬AI2종_실제구동_검증보고서.md'
    (EVIDENCE/report_name).write_text(report,encoding='utf-8')
    (output/report_name).write_text(report,encoding='utf-8')
    (EVIDENCE/'README.txt').write_text('이 폴더는 실제 요청·응답의 검증 증거입니다. 검증 보고서와 구동안내서를 먼저 읽으세요. unit-tests.log는 모의 응답을 이용한 자동 회귀시험 로그로, 실제 모델 실행 6건과 구분합니다.\n',encoding='utf-8')
    rawcfg=json.loads((ROOT/'config.example.json').read_text(encoding='utf-8'))
    profiles={k:v for k,v in rawcfg['llm']['profiles'].items() if k in ('local_gemma','local_llama')}
    (EVIDENCE/'local-model-profiles.json').write_text(json.dumps({'llm':{'active':'local_gemma','profiles':profiles}},ensure_ascii=False,indent=2),encoding='utf-8')
    files={p.name:p.read_bytes() for p in EVIDENCE.iterdir() if p.is_file() and p.name!='sha256.json'}
    files['로컬AI_2종_구동안내.md']=(ROOT/'docs'/'로컬AI_2종_구동안내_v12.md').read_bytes()
    files['reproduction/verify_local_models.py']=(ROOT/'tools'/'verify_local_models.py').read_bytes()
    screenshot=output/'local-ai-models.png'
    if screenshot.exists(): files[screenshot.name]=screenshot.read_bytes()
    manifest={name:hashlib.sha256(raw).hexdigest() for name,raw in sorted(files.items())}
    files['sha256.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    (EVIDENCE/'sha256.json').write_bytes(files['sha256.json'])
    package=output/'세션2_로컬AI2종_실제구동_제출증거.zip'
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,raw in sorted(files.items()): z.writestr(name,raw)
    with zipfile.ZipFile(package) as z:
        assert z.testzip() is None
        for name,digest in manifest.items(): assert hashlib.sha256(z.read(name)).hexdigest()==digest
    print('Verified package:',len(files),'files;',package.stat().st_size,'bytes')


if __name__=='__main__': main()
