# Mac 실행·운영 자동화

## 구성

`infra/compose.runtime.yml`은 개발용 Compose와 분리된 로컬 실행 구성입니다. PostgreSQL, Redis, MinIO, API, FFmpeg/STT 워커, 디스패처, 관리화면(Caddy), 상태 점검, 백업을 함께 실행합니다. DB·Redis·S3 관리 포트를 호스트에 공개하지 않습니다. 관리화면만 기본 `127.0.0.1:18444`에 연결합니다.

- 시작 시 비공개 버킷과 관리자 계정을 자동 생성합니다. 기존 계정 비밀번호는 덮어쓰지 않습니다.
- 비밀번호와 JWT 키는 무작위 생성하여 `.runtime/production.env`에 권한 0600으로 보관합니다. Git과 Docker 빌드 컨텍스트에서 제외합니다.
- API 준비 완료 후 워커·디스패처가 시작됩니다. 컨테이너는 `unless-stopped` 정책으로 재시작합니다. 별도 로그인 시작 설정은 Docker Desktop이 준비될 때까지 기다린 뒤 스택을 다시 실행합니다.
- 점검기는 60초마다 DB·Redis·저장소·워커를 확인하고 실패 작업 수를 기록합니다. 만료된 실행 점유는 중복 방지 키와 함께 다시 큐에 넣습니다. 불명확한 유료 호출은 기존 워커의 확인 절차에서 멈춥니다.
- DB는 시작 시와 매일 백업합니다. 영상은 별도 호스트 폴더에 증분 백업하며 기존 백업 파일은 삭제하지 않습니다. 이 백업도 같은 Mac에 있으므로 기기 자체 손실 대비에는 외부 디스크/원격 복제가 추가로 필요합니다.
- 원본·승인 결과물은 자동 삭제하지 않습니다. 보관 기간과 외부 백업 목적지가 정해진 뒤 삭제 정책을 추가합니다.
- 외부 오류 알림은 `R4_ALERT_WEBHOOK_URL`을 설정하면 상태 변경 시 전송합니다. 기본은 로컬 상태 파일·컨테이너 로그이며 수신 채널은 연결되어 있지 않습니다.

기준 문서: [Compose 시작 순서](https://docs.docker.com/compose/how-tos/startup-order/), [컨테이너 재시작](https://docs.docker.com/engine/containers/start-containers-automatically/), [Caddy 프록시](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [MinIO 공식 컨테이너 안내](https://github.com/minio/minio/blob/master/docs/docker/README.md). Docker Hub의 기존 MinIO 경로에서 이미지 다운로드가 실패하여 공식 Quay 경로로 변경했습니다. 사용 이미지는 로컬 검증용 기존 고정 릴리스이며, 인터넷 공개 전 저장소 제품·보안 업데이트 정책을 재평가해야 합니다.

## 실행 명령

저장소 루트에서 Python 3.11 이상과 Docker Desktop을 사용합니다.

```bash
python3 scripts/ops.py init
python3 scripts/ops.py up
python3 scripts/ops.py status
python3 scripts/ops.py check
python3 scripts/smoke.py
python3 scripts/ops.py backup
python3 scripts/ops.py restore-check
python3 scripts/ops.py install-startup
```

`smoke.py`는 실제 S3 업로드, ffprobe 원본 검사, Redis 전달, FFmpeg 세로 렌더, 결과 다운로드·디코딩을 확인합니다. 유료 호출·승인·YouTube 게시를 실행하지 않습니다. 결과는 `.runtime/smoke-final.mp4`, 실행 기록은 `.runtime/smoke-report.json`에 저장합니다. 기본 테스트는 제공된 대본을 사용합니다.

```bash
# 실제 파일에서 로컬 STT까지 검증. 영상은 최소 7초 이상 필요합니다.
python3 scripts/smoke.py --source /absolute/path/sample.mp4 --stt
```

`restore-check`는 최신 DB 백업을 임시 DB에 실제 복원하고 조회한 뒤 **검증용 DB만 삭제**합니다. 운영 DB에는 쓰지 않습니다. 파일 백업의 manifest에는 원본 키·크기·ETag·SHA-256과 저장 파일의 대응을 기록합니다.

종료는 `python3 scripts/ops.py stop`입니다. 데이터 볼륨을 삭제하는 명령은 제공하지 않습니다. 로그인 시작을 해제하려면 `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.recording4.stack.plist`를 실행하고 해당 plist를 별도로 보관하거나 삭제합니다. Mac이 잠자거나 꺼지면 처리가 멈추므로 24시간 운영에는 항상 켜진 서버가 필요합니다.

## 실제 계정 연결

1. `.runtime/production.env`에 [단계별 연결 설정](CONNECTED_WORKFLOW.md)의 프로젝트·키·가격 상한을 저장합니다. 기본 유료 처리와 업로드는 `false`입니다. 월·작업 예산을 설정하기 전에는 유료 처리로 바꾸지 않습니다.
2. Google ADC 및 YouTube OAuth JSON은 Git 밖에 저장합니다. `worker.connect_youtube` 명령으로 사용자가 직접 계정 로그인을 완료해야 합니다. 사용자 계정의 동의 절차는 자동 승인하지 않습니다.
3. Docker의 `provider_secrets` 볼륨 또는 읽기 전용 bind mount로 워커에 인증 파일을 전달하고 UID 10001이 읽을 수 있도록 설정합니다. `.env`의 경로는 컨테이너 경로여야 합니다. 비밀 파일의 내용을 로그나 PR에 넣지 않습니다.
4. `python3 scripts/ops.py up`으로 새 설정을 적용합니다. 관리화면에서 월 예산·작업 예산·음성을 지정하고 비공개 샘플을 검증합니다.
5. 인터넷 HTTPS를 사용하려면 소유 도메인과 배포 주소가 필요합니다. `R4_SITE_ADDRESS`에 도메인, `R4_S3_PUBLIC_ENDPOINT_URL`에 같은 HTTPS 주소, `R4_BIND_IP`와 80/443 포트를 구성하면 Caddy의 인증서 발급 경로를 사용할 수 있습니다. 현재는 Mac 내부 전용 HTTP이며 외부 HTTPS가 개통된 상태가 아닙니다.

## 복구·한계

- DB 원본·백업·비밀 파일은 모두 중요합니다. 외부 복제와 보관 기간은 아직 사용자 설정 대상입니다.
- 알림 URL에는 민감한 오류 원문 대신 상태와 건수만 보냅니다.
- 유료 공급자·YouTube 실계정 검증은 자격증명과 비용 한도가 설정된 뒤 진행합니다.
- 영상 검수와 버전 승인은 계속 명시적인 사용자 작업입니다. 자동화가 승인되지 않은 영상을 공개하지 않습니다.
