# 배포 대상

- GitHub: `visanu81/gongmudam` 비공개 저장소
- 요청한 서비스 주소: **https://gongmudam.visanu81.workers.dev**
- 현재 상태: GitHub 보관·실행 준비. 이 주소의 Workers 배포와 실제 API 연결은 아직 수행하지 않았습니다.

## 현재 실행 구조

| 구성 | 실행 방법 | 로컬 주소 | 상태 |
|---|---|---|---|
| 기존 업무 기능 v69 | `install-service.bat` → `run-service.bat` | `http://127.0.0.1:8781/start.html?v=69` | FastAPI·공개 원문·SQLite·선택적 로컬 AI |
| 공무담 B안 | `run-desktop.bat` | `http://127.0.0.1:8891/` | 기관 검색·계산기·메모장 실제 동작, 나머지 업무 화면은 시안 |

두 실행 환경은 현재 분리되어 있습니다. GitHub에 두 폴더를 보관했다는 것이 B안의 출장·취합 화면과 기존 서비스 API가 통합되었다는 뜻은 아닙니다.

## Workers 연결 시 필요한 작업

Cloudflare는 Python Workers에서 FastAPI를 지원합니다. 공식 예시는 Workers용 ASGI 진입점과 정적 자산 바인딩을 사용합니다. 현재 `uvicorn`, 로컬 SQLite 파일, PC 폴더 감시, 로컬 모델 서버에 맞춘 이 프로젝트의 실행 코드를 그대로 배포한 것으로 간주할 수 없습니다.

전체 기능을 같은 주소로 제공하려면 아래 사항을 정해야 합니다.

1. B안과 기존 업무 API 연결, 실제 처리 화면 통합.
2. 서비스 API를 실행할 환경과 영속 데이터 저장소. Workers에서 직접 실행한다면 런타임·데이터 접근을 맞춰야 합니다.
3. 로컬 AI·PC 폴더는 해당 PC 또는 별도 연결 프로그램과 통신할 경로가 필요합니다. 클라우드의 `127.0.0.1`은 사용자의 PC가 아닙니다.
4. 다른 사람이 사용할 업무·원문·첨부 자료의 사용자 구분과 접근 범위.
5. 배포 후 요청한 주소에서 실제 검색·질문·첨부·재접속을 확인.

이 저장소에는 연결되지 않은 업무 기능을 작동하는 서비스처럼 공개하는 자동 배포 워크플로를 넣지 않았습니다. 배포 완료 상태나 실제 API 주소·토큰을 꾸며 넣지 않습니다.

공식 참고: [Python Workers의 FastAPI](https://developers.cloudflare.com/workers/languages/python/packages/fastapi/), [데이터 저장소 선택](https://developers.cloudflare.com/workers/platform/storage-options/).
