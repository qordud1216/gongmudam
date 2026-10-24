# 공무담 배포 구조

공개 주소: **https://gongmudam.visanu81.workers.dev**

2026-10-24 Workers 배포와 B안의 기존 v69 기능 연결을 완료했습니다. Python 서버 자체를 Workers로 이식한 배포는 아닙니다.

```text
방문자 → Workers 정적 B안
         └─ 업무 화면·API → 전용 VPC 서비스 → 전용 Tunnel
                           → 운영 PC의 별도 FastAPI 실행본(127.0.0.1:8892)
                             ├─ 공개 시연 DB·공개 원문
                             └─ 로컬 Ollama Gemma / Llama
```

## 실행과 유지

- 처음 설치: `install-service.bat`. 운영 도구는 Node.js 설치 후 `npm ci`.
- 업무 서버: `run-gongmudam.bat`. 통합 로컬 주소는 `http://127.0.0.1:8892/`.
- 공개 연결: 별도 터미널에서 `run-tunnel.bat`. 해당 Cloudflare 계정 권한이 필요합니다.
- Workers 화면·코드 갱신: `npm run deploy`.
- PC·서버·터널을 끄면 실제 업무와 AI는 사용할 수 없습니다. B안 정적 화면은 열리며 연결 실패를 안내합니다.
- 다시 실행해도 같은 Workers 주소를 사용합니다. 이번 작업은 Windows 부팅 시 자동 실행을 등록하지 않습니다.

운영 PC에는 Python 3.12 x64와 선택적으로 Ollama의 `gemma3:4b`, `llama3.2:3b`가 필요합니다. 모델을 사용하지 않는 원문 안내·규칙 계산·파일 처리는 AI 응답과 구분됩니다.

## 연결 범위

바탕화면에서 실제 서무 안내·출장정산·자료 취합·업무자료 정리·도구함·변경 알림함을 같은 출처의 창으로 엽니다. 창 최소화·복원, 계산기·메모장을 유지합니다. 최근 업무는 저장 API에서 읽으며 등록 원문 폴더를 진행 업무처럼 표시하지 않습니다. 날짜 버튼은 업무 달력을 엽니다.

소속은 브라우저에 저장하고 질문에 함께 전달합니다. 질문에서 적용 대상을 지정하면 이를 우선합니다. 출장 계산은 정산 화면에서 적용 기관·규정팩을 확인해야 합니다. 기관 검색만으로 계산팩 검수나 지급 승인을 자동 완료하지 않습니다.

## 공개 시연 경계

링크를 가진 사람이 들어오는 공개 시연입니다. 방문자가 만든 업무와 첨부는 같은 시연 DB에서 보입니다. 소속·메모는 각 브라우저 저장소에 남습니다. 실제 개인정보·업무자료는 입력하지 마세요.

- `.local-runtime/service`에 새 실행본을 만들며 기존 개인 DB·설정은 복사하지 않습니다. 재실행 시 공개 업무를 보존합니다.
- 폴더 연결은 합성 시연 폴더와 등록 공개 원문 폴더로 제한합니다. 임의 PC 폴더는 연결하지 않습니다.
- 모델 설정은 고정 Gemma·Llama 중 선택만 허용합니다. 외부 서버 주소·키 삽입을 차단합니다.
- 공개 업로드는 12MB 이하이며 도구별로 더 작은 제한이 적용될 수 있습니다.
- 모델 요청과 연결 확인에 동시 실행·시간당 횟수 제한을 적용합니다.
- Workers에는 화면 자산만 배포합니다. 기관 SQLite·Python·업무 DB·설정은 정적 자산에 포함하지 않습니다.
- 전용 VPC 서비스는 공무담 포트에만 연결합니다. 다른 프로젝트의 터널을 재사용하지 않습니다.

## PC 의존성을 없애려면

Workers도 Python/FastAPI를 지원합니다. 현재 앱의 SQLite·파일·폴더 감시·AI를 옮기려면 영속 DB·첨부 저장소·실행 환경을 이식해야 합니다. 실제 기관 업무 운영에는 사용자별 데이터와 인증 분리도 필요합니다.

공식 문서: [Workers의 FastAPI](https://developers.cloudflare.com/workers/languages/python/packages/fastapi/), [VPC 서비스](https://developers.cloudflare.com/workers-vpc/configuration/vpc-services/), [Tunnel](https://developers.cloudflare.com/workers-vpc/configuration/tunnel/).
