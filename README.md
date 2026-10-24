# 공무담

공무담은 Windows에서 실행하는 공무 업무 도우미입니다. 이 폴더에는 전체 서비스와 별도로 실행되는 승인된 데스크톱 디자인 시안이 함께 있습니다.

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

`desktop/`은 공무담과 수달 마스코트 무무를 담은 승인된 B형 화면입니다. 공식 기관 검색, 계산기, 메모장을 포함하지만 업무 화면과 AI 대화는 예시 데이터이며 전체 서비스 API와 아직 통합되지 않았습니다. 메모와 소속 시안 설정은 브라우저 로컬 저장소에 저장됩니다.

`run-desktop.bat`을 실행한 뒤 <http://127.0.0.1:8891/>을 엽니다. Python 패키지 설치는 필요하지 않습니다.

## 배포 및 확인

요청된 공개 주소는 <https://gongmudam.visanu81.workers.dev>이며 현재 배포되었거나 작동하는 주소가 아닙니다. GitHub 저장소는 [visanu81/gongmudam](https://github.com/visanu81/gongmudam)이며 비공개입니다. 접근하려면 저장소 권한이 필요합니다.

Cloudflare 배포, 로컬 파일 접근, AI 연결, 업무 폴더 연동에는 호스팅 환경에 맞는 별도 작업이 필요합니다. 배포 계획은 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), 검증 기록은 [docs/VERIFICATION.md](docs/VERIFICATION.md)를 참고하세요.
