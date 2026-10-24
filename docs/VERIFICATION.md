# GitHub 보관본 검증 — 2026-10-24

이 기록은 기존 업무 서비스 v69와 공무담 B안을 새 폴더에 복사해 GitHub에 보관하기 위한 확인 결과입니다. 기존 실행 서버·업무 DB·브라우저 소속·메모는 변경하지 않았습니다. 다른 물리 PC에서의 검증은 아니며, 같은 Windows PC의 새 폴더와 새 가상환경에서 확인했습니다.

## 이번에 실행한 확인

| 항목 | 결과 |
|---|---|
| v69 제출본의 런타임 파일 483개 | 원본 manifest SHA-256과 모두 일치 |
| B안 소스·자산·공개 기관 DB 21개 | 복사 전후 SHA-256 모두 일치 |
| `install-service.bat` 실행 | 새 Python 3.12 가상환경 생성, 번들 wheel만으로 설치 성공 |
| `pip check` | 의존성 오류 없음 |
| 제출 자료 복원 | 공개 법령·지침 25건 및 매뉴얼 6건, 합계 31건 복원 |
| 복원 후 등록 자료 | 31건 모두 활성화되어 있고 현재 원문 해시와 일치 |
| 서비스 화면·API | 시작·출장·도구함 화면, 출장 bootstrap, 등록 자료 API 모두 HTTP 200 |
| B안 HTTP | B 화면, 상태 조회, 경기도청 기관 검색 모두 HTTP 200 |
| 기관 검색 단위 테스트 | 8개 통과 |
| 자바스크립트 문법 | desktop·agency-picker·calculator·notepad 4개 파일 통과 |
| 업로드 후보 검사 | 개인 설정·실행 DB·로그·가상환경 제외, 알려진 토큰 패턴 및 파일 크기 검사 통과 |

서비스 HTTP 검사는 FastAPI TestClient로 실행했고, B안은 복사본 서버를 임시 포트에서 실제 HTTP로 호출했습니다. 이 확인에서는 서비스의 폴더 감시·규정 모니터 백그라운드 작업을 시작하지 않았으며, AI 모델을 호출하지 않았습니다. 테스트 도중 TestClient의 httpx 사용에 관한 폐기 예정 경고가 있었으나 요청과 검사는 모두 성공했습니다.

## 기존 v69 검증과의 구분

원본 v69 제출 패키지는 Python 761개 및 JavaScript 21개 검사, 실제 모델 검증 4건을 통과한 기록을 갖고 있습니다. 모델 최초 로딩 중 시간 초과 1건은 성공 건수에서 제외된 기록입니다. 이번 GitHub 업로드에서는 그 전체 검증을 다시 수행하지 않았으며, 검증된 실행 소스를 해시로 보존하고 위의 설치·자료 복원·HTTP·기관 검색 검사를 새로 실행했습니다.

원본 제출 ZIP의 SHA-256:

`94f3cba75e97d4cfa9465d0f7a4c59374f6c941dc84002d645d8fe384b00b7b8`

출처와 개별 B안 파일 해시는 [source-provenance.json](source-provenance.json), 서비스 파일 해시는 [submission-manifest.json](../service/submission-manifest.json)에 있습니다.

## 다시 확인하는 방법

저장소 최상위에서 실행합니다.

```powershell
.\install-service.bat
.\service\.venv\Scripts\python.exe tools\audit_repository.py
.\service\.venv\Scripts\python.exe -m unittest discover -s desktop/tests -v
```

자바스크립트 문법 검사는 별도로 설치한 Node.js의 `node --check desktop/파일명.js`로 실행할 수 있습니다. Node.js는 일반 앱 실행의 필수 조건이 아닙니다.

## 현재 남은 연결

B안의 기관 검색·계산기·메모장은 작동하며, 업무 화면과 AI 대화는 시안입니다. 기존 서비스와 B안의 API 연결 및 `gongmudam.visanu81.workers.dev` 배포는 아직 수행하지 않았습니다. 이 저장소 업로드를 클라우드 서비스 가동이나 다른 PC에서의 모델 연결 검증으로 해석하면 안 됩니다. 실행 방법은 [README](../README.md), 배포 고려 사항은 [DEPLOYMENT.md](DEPLOYMENT.md)에 있습니다.
