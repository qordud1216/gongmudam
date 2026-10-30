# PC 독립 클라우드 릴리즈

이 경로는 기존 CPython 3.12/FastAPI를 상시 Docker 호스트와 영속 볼륨에서 실행한다. Cloudflare 입구는 `cloudflare/cloud-worker.js`이며 모든 화면·자산·API·원문·다운로드를 인증하는 백엔드로 전달한다. 기존 `cloudflare/worker.js`와 Windows 공개 시연 실행기는 별도 보존한다. 호스트 상품·예산·실제 Access 정책은 이 코드로 생성하지 않는다.

## 릴리즈 계약

- 첫 운영 범위는 **인증된 운영자 한 명**이다. 공용 가입·기관별 다중 사용자 격리를 구현했다고 표시하지 않는다. Access의 서명·issuer·audience·만료를 검증하고 지정한 이메일 하나만 허용한다. 인증 없이 허용되는 `/health/live`는 `alive`만 반환한다. 다른 기본 접속 주소도 Access 정책 또는 백엔드 서명 검사를 거쳐야 한다.
- `GONGMUDAM_DATA_ROOT`는 코드 밖의 영속 볼륨이다. 설정·업무/달력/여비/자료함 DB·첨부·원문 사본·출력물을 이곳에 보관한다. 시작은 기존 볼륨을 검증하며 초기화·자료 재등록·DB 복원은 수행하지 않는다. 단일 실행 인스턴스를 파일 잠금으로 강제한다. SQLite 파일을 네트워크 공유 또는 여러 쓰기 인스턴스로 확장하지 않는다.
- 클라우드 진입점은 서버에서 LLM을 차단한다. 모델 서버·키 없이 시작하며 설정 변경, 직접 제공자 호출, 모델 확인/분류/작성 요청도 추론을 수행하지 않는다. `use_ai:false`는 기존 시연의 AI 요청 한도를 소비하지 않는다. Solar는 연결하지 않았다.
- 기관 코드·상위기관·부서·신분 선택, 검색과 직접 원문 인용·미확정 표시, 규칙 계산, 업무·달력, 업로드/다운로드·내보내기 경로를 유지한다. 등록된 보관 자료의 범위이며 실시간 법령 API가 추가된 것은 아니다. 법적 승인·기관 적용성·현행성을 새로 부여하지 않는다.
- PC 네이티브 폴더 선택/지속 감시는 브라우저 업로드 사본으로 대체한다. 원래 PC 파일과 자동 동기화하지 않는다. Linux의 사진 OCR은 기존 수동 입력 대체를 표시한다. 텍스트 PDF/파일 업로드는 유지한다. Windows OCR 제거·새 OCR 설치는 하지 않는다.
- 클라우드 시작 시 폴더 AI 감시·규정 모니터를 자동 가동하지 않는다. 규정 갱신/검토 쓰기 API는 별도 검수 절차 안내로 거부한다. 코드 배포가 미검수 법률자료 승격으로 이어지지 않는다.

## Git 변경과 빌드

`.github/workflows/cloud-release.yml`은 작업 브랜치 push/PR/수동 실행에서 Python·기관·Worker·화면 논리 시험, 패키지 빌드, 비루트 컨테이너의 실제 HTTP·재시작 저장 시험을 수행한다. 원격 CI 성공은 해당 실행 결과로 확인해야 한다. 이 워크플로는 호스트 가입·토큰 생성·공개 배포를 하지 않는다.

```sh
python -m pip install -r service/requirements-cloud.lock.txt
PYTHONPATH=service:. python -m unittest discover -s service/tests -v
PYTHONPATH=service:. python -m unittest discover -s desktop/tests -v
PYTHONPATH=service:. python -m unittest discover -s tests -v
node --test tests/*.test.mjs
node --test service/tests/*.test.cjs
python tools/build_cloud_release.py --output dist/cloud-release
```

빌더는 Git의 허용된 소스만 포함하며 개인 `config.json`, DB, 업로드, 키, 로컬 runtime, Windows wheel을 복사하지 않는다. 기관 SQLite는 기존 읽기 전용 스냅샷을 백엔드에 포함한다. 런타임 입력 자료는 이미 저장소에 있는 제출 번들만 사용한다. 현재 PC의 등록 자료를 검색·내보내지 않는다.

원본 `service/submission-manifest.json`은 그대로 보존한다. 새 `development-release.json`은 별도 개발 릴리즈의 실제 파일 해시·소스 커밋·릴리즈 ID를 기록한다. 원본 봉인의 승인이나 법률자료의 정답 판정을 뜻하지 않는다. 수정 소스로 원본 `tools/prepare_public_runtime.py`를 실행하면 봉인 불일치로 거부되는 것이 정상이다. 클라우드 경로는 원본 봉인을 PASS로 변경하거나 우회 실행하지 않고 별도 개발 패키지를 검증한다. `--allow-dirty`는 로컬 개발 시험 전용이며 승격 도구는 이를 거부한다.

CI는 같은 커밋에서 `cloud-release.tar.gz`, `gongmudam-image.tar.gz`, `image-id.txt`, manifest·SHA256 영수증을 만든다. 내려받은 산출물 폴더에서 `sha256sum -c SHA256SUMS`로 확인한다. 미리보기에서 검증한 **동일 이미지 ID/산출물**을 운영으로 승격하며 재빌드하지 않는다. 백엔드 상태와 미리보기 영수증의 image ID까지 대조한다. 수정이 생기면 새 CI 산출물과 새 미리보기 검증이 필요하다. 자동 호스트 갱신 연결은 선택한 호스트와 기존 승인 자격증명을 확인한 후 연결한다.

## 승인된 기존 호스트에서 첫 미리보기

상시 호스트, 저장 용량/지역/예산, Docker 실행 권한과 사용자 소유 Tunnel/VPC·Access 설정을 먼저 확인한다. 원저자의 account/tunnel/service ID를 재사용하지 않는다. 개발 PC는 시험 호스트와 별개이며 PC를 꺼도 선택한 서버가 운영되는 구조다. 단일 서버 구성은 고가용성 또는 무중단 배포를 보장하지 않는다.

1. CI 산출물을 내려받아 SHA256을 대조하고 소스와 이미지 아카이브를 확인한다. 이미지 로드 후 `docker image inspect`에서 불변 image ID를 기록한다.
2. 운영 볼륨과 다른 `gongmudam-preview-*` 이름을 선택한다. `deploy/runtime.env.example`을 저장소 밖에 복사해 승인된 Access team domain/audience와 운영자 이메일 **이름에 해당하는 설정값**만 구성한다. 키/토큰을 Git·이미지·채팅에 넣지 않는다.
3. 새로운 빈 볼륨에만 아래 초기화를 명시적으로 실행한다. 기존 소유 표식이 있으면 보존하고, 소유권이 불명확한 기존 데이터는 거부한다. 최초 보관 자료는 현행 전체 법령이나 검수 완료 자료로 자동 승격되지 않는다.

```sh
gzip -dk gongmudam-image.tar.gz
docker load --input gongmudam-image.tar
# 아래 셸 변수는 검증한 산출물/승인된 환경에 맞춰 운영자가 설정한다.
docker run --rm --mount type=volume,src="$GONGMUDAM_VOLUME_NAME",dst=/var/lib/gongmudam \
  "$GONGMUDAM_IMAGE" python tools/cloud_release.py initialize --data-root /var/lib/gongmudam
python tools/promote_cloud_release.py --release-directory ./cloud-release --environment preview \
  --image-id "$GONGMUDAM_IMAGE" --volume "$GONGMUDAM_VOLUME_NAME" \
  --runtime-env-file "$GONGMUDAM_RUNTIME_ENV_FILE"
```

기본은 계획 검사이며 실행하려면 검토한 동일 명령에 `--apply`를 명시한다. Compose는 호스트 포트를 공개하지 않는다. 초기화하지 않은 볼륨, 누락된 인증 설정 또는 다른 릴리즈 ID면 시작/승격을 거부한다. 시작 시 데이터 포맷 1을 유지하며 migration을 자동 실행하지 않는다.

Tunnel은 승인된 기존 토큰 파일을 `CLOUDFLARED_TOKEN_FILE`로, 검증한 이미지 digest를 `CLOUDFLARED_IMAGE`로 지정한 경우에만 `compose.tunnel.yml`을 사용한다. 토큰 값은 읽어 출력하지 않는다. Tunnel 컨테이너는 앱 네트워크 공간을 공유하고 VPC는 `127.0.0.1:8892`만 연결한다.

## Cloudflare 입구와 미리보기 확인

`CLOUDFLARE_ACCOUNT_ID`, `GONGMUDAM_VPC_SERVICE_ID`, 환경별 `GONGMUDAM_WORKER_NAME`을 승인된 기존 리소스에서 확인한다. 다음 도구는 `workers_dev:false`, `preview_urls:false`, 빈 routes를 기본으로 만들며 Access 정책을 생성하지 않는다.

```sh
python tools/render_cloudflare_config.py --environment preview --release-id "$GONGMUDAM_RELEASE_ID" \
  --output ./private-generated/worker-preview.json
# 실제 배포는 기존 계정 접근·권한·노출 범위를 확인한 뒤 이 생성 파일로 진행한다.
# npx wrangler deploy --config ./private-generated/worker-preview.json
```

기존 리소스와 Access가 확인된 경로를 연결한 후 실제 URL에서 로그인/로그아웃, 화면·iframe·원문·다운로드, 업로드와 재시작, 기관/부서 유지, 검색 인용·미확정·규칙·업무·달력을 시험한다. workers.dev/버전 URL/별칭/custom domain과 원본 서버를 통한 우회 경로도 확인한다. 설정 파일을 만들었다고 비공개 접근 검증이 끝난 것은 아니다.

기존 운영자 Access assertion을 환경 변수 `GONGMUDAM_ACCESS_JWT`로 제공한 읽기 시험은 다음과 같다. 새 토큰 발급이나 키 설정은 이 도구가 하지 않는다.

```sh
python tools/verify_cloud_preview.py --url "$GONGMUDAM_PREVIEW_ORIGIN" \
  --release-id "$GONGMUDAM_RELEASE_ID" --source-commit "$GONGMUDAM_SOURCE_COMMIT" --image-id "$GONGMUDAM_IMAGE" \
  --output preview-http-receipt.json
```

이 영수증은 실제 HTTP 확인만 표시하며 수동 외부 UI 성공을 자동 생성하지 않는다. 운영 승격에는 이 커밋/릴리즈와 일치하는 영수증, 운영자의 별도 UI 검증 기록, 일관 백업을 요구한다. 미리보기 데이터는 운영으로 자동 복사하지 않는다.

## 백업·복원·운영 승격·롤백

앱/Tunnel을 정지한 뒤 볼륨을 백업한다. 실행 중인 앱이 잠금을 소유하면 백업은 거부된다. SQLite backup/integrity_check와 첨부·원문 해시를 함께 보관한다. 백업은 개인정보를 포함할 수 있으므로 공개 CI 산출물/Git에 업로드하지 않는다. 승인된 비공개 백업 저장소의 암호화·보존기간은 호스트 선정 시 정한다.

```sh
python tools/cloud_backup.py backup --data-root /path/to/stopped-volume --staging-root /private-backup/work \
  --output /private-backup/gongmudam-backup.tar.gz > /private-backup/receipt.json
python tools/cloud_backup.py restore --archive /private-backup/gongmudam-backup.tar.gz \
  --sha256 "$RECORDED_BACKUP_SHA256" --data-root /path/to/new-empty-volume --staging-root /private-backup/work
```

컨테이너 볼륨은 정지한 뒤 동일 불변 이미지의 일회 실행에 데이터 볼륨과 별도 백업 디렉터리를 마운트해서 이 명령을 실행한다. 전체 복사본을 `/tmp`의 128MiB tmpfs에 넣지 않는다. staging 기본값도 백업 아카이브가 있는 디스크이며 충분한 비공개 디스크 공간을 확보한다. 실행 중인 SQLite 파일을 임의 복사하지 않는다. 복원은 새 빈 볼륨에만 수행하며 경로·중복·링크·해시·DB 무결성을 검증하고 저장 경로를 명시적으로 재배치한다. 기존 볼륨은 덮어쓰지 않는다.

`promote_cloud_release.py --environment production`에 `--preview-receipt`, `--ui-verification-note`, `--backup-receipt`, `--backup-archive`를 추가해 먼저 계획을 검사한 뒤 `--apply`한다. 운영 볼륨 이름은 `gongmudam-production-*`이어야 한다. Worker와 백엔드는 같은 release ID를 사용한다. 전환 중 ID가 다르면 503을 반환한다.

롤백은 이전 검증 이미지 ID와 그 manifest/Worker 버전을 함께 되돌린다. 코드 롤백이 DB·첨부를 되돌리지는 않는다. 데이터 포맷이 호환되지 않는 migration은 별도 계획·백업·복원 시험 없이는 적용하지 않는다. 데이터 복원은 코드 롤백과 별도로 운영자가 선택하며 복원 이후 입력 유실 범위를 확인한다.

공식 근거: [Workers VPC](https://developers.cloudflare.com/workers-vpc/get-started/), [Access JWT 검증](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/), [Workers 롤백](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/), [SQLite 백업](https://www.sqlite.org/backup.html).
