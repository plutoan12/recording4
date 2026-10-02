# Mac의 최신 서버본 검수

2026-10-02 기준 검수 대상은 artifact `2714865c-970a-4ba2-ab71-0ad9c504e57a`다. 32.6초·720×1280 영상에 기존 한국어 자막과 원음을 유지하고28.8–30.63초의 영역 모자이크를 추가했다. 사람 청취와 전체 영상 검수는 대기 상태다.

## 화면과 파일

- 화면: http://127.0.0.1:8767/
- 기존 서버/HTML/영상 위치: `/Users/an-youwon/Projects/recording4-deliveries/20260929-6LVyV8ueYc8/qa-20260930-server-mask-fixed`
- 새 로컬 묶음: `/Users/an-youwon/Projects/recording4-deliveries/20260929-6LVyV8ueYc8/review-handoff-20261002/recording4-server-review-2714865c.zip`
- 묶음 내용: `final-server-review.mp4`, `captions-server.srt`, `captions-server.vtt`, `manifest.json`, `검수안내.md`

manifest는 결과물/원본 ID, 세 파일의 SHA-256과 크기, 미검수·미승인 상태를 기록한다. ZIP의 CRC와 세 파일의 원본 해시 일치를 확인했다. ZIP SHA-256은 `e044e2fa2f722e2e0fcd2bbaafe8a64fa2cdbbe1f6def231b66e333550efad8d`다. 원시 영상·음성·전사·ZIP은 Git에 넣지 않는다. 이전 `recording4-review-20260930.zip`은 다른 로컬 보완본이므로 최신 서버본으로 혼동하지 않는다.

## 확인할 내용

1. 화면의 구간 재생으로0–5초,25–29.74초,28.7–32.6초를 직접 듣는다. 필요한 대사를 고치고 직접 확인한 항목만 체크한다.
2. **검수 결과 저장**으로 JSON을 내려받아 Codex에 첨부한다. 입력은 화면을 닫기 전에 저장한다. 파일명은 `caption-review.server-2714865c.reviewed.json`이며 미확인 항목이 있으면 `partial`로 저장된다.
3. 전체 영상의 자막 내용/시각, 음질, 얼굴 가림 누락과 과도한 가림을 확인하고 문제가 있으면 시각과 함께 기록한다. 세 구간 JSON만으로 전체 영상 검수가 완료되지 않는다.

영상에는 자막이 이미 들어 있다. SRT/VTT를 플레이어에서 동시에 켜면 자막이 두 겹으로 보일 수 있다. 저장한 검수 JSON은 게시 승인이 아니며 파일이 변경되면 이전 버전의 확인·승인을 재사용하지 않는다.

## 로컬 실행 관리

사용자 LaunchAgent `~/Library/LaunchAgents/com.recording4.delivery-review.plist`가 기존 `serve_review.py`를 실행한다. 설정은 `RunAtLoad=true`, `KeepAlive=true`, `ThrottleInterval=10`이며 Python 실행 파일은 `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3`다. 이 Mac의 로그인 세션에서만 동작하고 Mac이 꺼지거나 잠자기 상태일 때의 접속은 보장하지 않는다. 외부 공개 주소가 아니다.

```sh
# 상태 확인
launchctl print "gui/$(id -u)/com.recording4.delivery-review"

# 검수 서버 중지: 영상/자막/입력 파일을 지우지 않음
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.recording4.delivery-review.plist"

# 중지한 서버 재개
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.recording4.delivery-review.plist"
```

로그는 `/Users/an-youwon/Projects/recording4-local-tools/review-services/server-2714865c/`에 있다. 운영 스택의 별도 `com.recording4.stack.plist`는 수정하지 않았다. 시간별 품질 개선 자동화 `recording4`의 PAUSED 상태와 이 읽기 전용 파일 서버 실행은 별개다.

## 이번 확인 범위

페이지/MP4/SRT/VTT의 HTTP200 및 파일 해시 일치, 비허용 경로3개의404, POST501을 확인했다. localhost에만 수신하는 것을 확인했다. 서버 프로세스를 SIGTERM으로 종료한 뒤 새 PID가5.695초에 HTTP200으로 복구됐다. 브라우저에서32.6초·720×1280 영상 로드와 세 청취 체크 미선택을 확인했다. 실제 Mac 재부팅/로그인, 사람 청취, 전체 얼굴 검출률은 이 확인에 포함되지 않는다. 애플리케이션 소스나 모델 입력이 바뀌지 않아 기존 CI/모델 검사는 반복하지 않았다.
