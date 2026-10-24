# 공무담

공무담은 공무 업무 도우미입니다. 승인된 B안 바탕화면에서 기존 v69의 출장정산·자료 취합·업무자료 정리·업무도구함·변경 알림함을 창으로 열어 사용합니다.

공개 주소: **https://gongmudam.visanu81.workers.dev**

Workers에 배포된 화면은 PC의 별도 업무 서버·로컬 AI에 연결됩니다. 해당 PC와 서버·터널이 켜져 있어야 업무 처리가 됩니다. 방문자들이 같은 합성 업무를 공유하는 공개 시연이므로 실제 개인정보·업무자료는 입력하지 마세요.

## 준비 환경

- Windows
- Python 3.12 x64 (`py -3.12` 실행 가능)

## 전체 서비스

`service/`에는 검증된 v69 FastAPI 앱이 포함되어 있습니다. 패키지에 포함된 25개 공개 법령과 6개 업무 매뉴얼, 테스트, wheel 파일, 오프라인 설치 구성은 보존되어 있습니다. 개인 데이터베이스, 사용자 설정, 모델 가중치는 포함하지 않습니다.

1. `install-service.bat`을 실행합니다.
2. `run-service.bat`을 실행합니다.
3. 브라우저에서 <http://127.0.0.1:8781/start.html?v=69>을 엽니다.

8781 포트를 이미 사용 중이면 `run-service.bat --port 8787`로 시작합니다.
AI 모델 연결은 선택 사항이며 별도로 운영하는 Ollama를 사용할 수 있습니다.

## 데스크톱 시안

`desktop/`은 공무담과 수달 마스코트 무무를 담은 B형 화면입니다. 업무 창은 기존 서비스 API를 사용합니다. 메모·소속은 브라우저에 저장되며 소속은 질문에 함께 전달됩니다. 출장 계산에 적용할 기관·규정팩은 출장 화면에서 확인합니다. 로컬 주소와 공개 주소의 브라우저 저장 공간은 서로 다릅니다.

`run-desktop.bat`을 실행한 뒤 <http://127.0.0.1:8891/>을 엽니다. Python 패키지 설치는 필요하지 않습니다.

이 명령은 기관 검색용 단독 화면 서버입니다. 실제 업무 기능은 다음 통합 실행을 사용하세요.

## 통합 실행·공개 연결

1. 처음에는 `install-service.bat`을 실행합니다.
2. `run-gongmudam.bat`을 실행하고 <http://127.0.0.1:8892/>를 엽니다.
3. 공개 주소를 연결할 운영 PC에는 Node.js를 설치하고 `npm ci`를 실행합니다. 별도 터미널에서 `run-tunnel.bat`을 실행합니다. 해당 Cloudflare 계정의 로그인 권한이 필요합니다.

통합 실행은 `.local-runtime/service`에 별도 공개 시연 실행본을 만듭니다. 기존 개인 DB·설정은 복사하지 않으며, 다시 실행할 때 공개 시연 업무를 보존합니다. Workers 화면·코드를 갱신할 때는 `npm run deploy`를 사용합니다. 다른 Cloudflare 계정에서는 전용 터널·VPC 서비스를 만들고 `wrangler.jsonc`를 변경해야 합니다. 자격증명은 저장소에 넣지 않습니다.

## 배포 및 확인

공개 주소는 <https://gongmudam.visanu81.workers.dev>입니다. GitHub 저장소는 [visanu81/gongmudam](https://github.com/visanu81/gongmudam)이며 비공개입니다. 접근하려면 저장소 권한이 필요합니다.

배포 구조는 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), 이번 검증은 [docs/INTEGRATION-20261024.md](docs/INTEGRATION-20261024.md), 최초 GitHub 사본 검증은 [docs/VERIFICATION.md](docs/VERIFICATION.md)를 참고하세요.
