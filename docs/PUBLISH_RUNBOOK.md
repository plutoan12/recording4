# 게시 경로 실행 절차 (YouTube 비공개 업로드·예약)

이 절차는 **실제 계정에 영상을 올립니다.** 되돌릴 수 없고 API 할당량을 씁니다.
읽고 나서 실행하세요. 자동화하지 않습니다.

## 왜 문서로만 남기는가

게시 경로의 마지막 한 걸음은 CI에서 검증할 수 없습니다. OAuth 인증 파일이
있어야 하고, 그 파일은 계정 소유자의 컴퓨터에만 두는 것이 맞습니다. 클라우드
세션이나 CI 시크릿에 갱신 토큰을 올리면 그 토큰으로 계정의 영상을 올리고
지울 수 있습니다.

그래서 **코드 경로는 대역으로 검증하고, 실제 호출은 이 절차로 사람이
실행합니다.**

### 지금까지 검증된 것

| 구간 | 검증 방법 | 어디서 |
|---|---|---|
| 승인 없는 게시 차단, 중복 요청 병합, 상태 전이(uploading → scheduled → published) | 대역 YouTube로 실제 API·DB·워커 함수 호출 | `tests/test_connected_workflow.py` |
| 재개 업로드 규약(세션 재사용, 서버에 오프셋 다시 묻기, 완료된 업로드 재시도 안 함, 승인본이 다르면 중단) | **실제 Google SDK**를 가짜 YouTube 서버에 연결 | `tests/test_youtube_resumable.py` |
| 스택 전체 기동·실제 S3·제작 전 경로 | 운영 구성으로 기동 후 스모크 | CI `스택 기동 검증` 잡 |

### 아직 검증되지 않은 것

- **실제 YouTube API 응답**(할당량 오류, 처리 지연, 채널 정책 거절).
- 예약 워커의 실제 게시 전환(`scheduled` → `published`)은 YouTube가 공개로 바꾼 뒤에야 확인됩니다.
- 2026-09-18에 비공개 업로드 1회가 성공했지만 **독립 스크립트**로 했습니다. DB `Publication` 행을 만들지 않았으므로 예약 워커 전 경로를 검증했다고 보면 안 됩니다.

## 사전 조건

1. 결과물이 검수를 통과하고 **승인**되어 있을 것(`POST /artifacts/{id}/approve`).
2. 올릴 영상이 무엇인지 사람이 확인했을 것. 승인본의 체크섬이 게시 요청에 박힙니다.
3. 예약 공개 시각이 정해져 있을 것. 게시 API는 시간대를 포함한 미래 시각을 요구합니다.

## 1. OAuth 연결 (최초 1회)

Google Cloud 콘솔에서 데스크톱 앱 유형의 client_secrets JSON을 받아 둡니다.

```bash
python -m worker.connect_youtube ~/client_secrets.json ~/.runtime/youtube-token.json
```

브라우저 로그인이 열립니다. 끝나면 채널 이름과 채널 ID가 출력됩니다.
인증 파일은 0600으로 저장되고 기존 파일을 덮어쓰지 않습니다.

**이 파일을 저장소·CI·채팅에 올리지 마세요.**

## 2. 설정

`.runtime/production.env`에 넣고 스택을 다시 띄웁니다.

```
R4_YOUTUBE_UPLOAD_ENABLED=true
R4_YOUTUBE_CREDENTIALS_FILE=/run/secrets/youtube-token.json
R4_YOUTUBE_CHANNEL_ID=<1단계에서 출력된 채널 ID>
```

인증 파일은 워커 컨테이너의 `provider_secrets` 볼륨(`/run/secrets`, 읽기 전용)에
둡니다.

```bash
python3 scripts/ops.py up
python3 scripts/ops.py status
```

채널 ID가 틀리면 워커가 업로드 전에 멈춥니다. 설정 채널과 게시 요청 당시
채널이 다르면 거부합니다.

## 2.5. 올리기 전 점검 (먼저 이것부터)

```bash
R4_YOUTUBE_UPLOAD_ENABLED=true \
R4_YOUTUBE_CREDENTIALS_FILE=~/.runtime/youtube-token.json \
R4_YOUTUBE_CHANNEL_ID=<채널 ID> \
  python3 scripts/preflight_publish.py
```

업로드 직전까지 필요한 것을 모두 확인하고 **영상은 올리지 않습니다**
(`videos.insert`를 부르지 않습니다). 읽기 호출 한 번만 씁니다.

걸러 내는 것:

- 실행 설정이 꺼져 있음 → 워커가 업로드 직전에 막습니다.
- 갱신 토큰 없음 → 처음 한 번만 되고 다음부터 막힙니다.
- 업로드 권한 없음 → 업로드 때 거절당합니다.
- 인증 파일을 남이 읽을 수 있음 → 그 파일로 계정 영상을 올리고 지울 수 있습니다.
- **설정한 채널과 계정의 채널이 다름** → 이대로 올리면 승인한 것과 다른 채널에 영상이 남습니다. 되돌릴 수 없습니다.

여기서 다 통과한 뒤에 3단계로 갑니다.

## 3. 게시 요청

```bash
curl -sS -X POST http://localhost:18444/api/publications \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"artifact_id": "<승인된 결과물 ID>",
       "title": "<제목>",
       "description": "<설명>",
       "made_for_kids": false,
       "publish_at": "2026-09-30T12:00:00+09:00"}'
```

- 승인이 없으면 409입니다. 승인 먼저 하세요.
- 같은 승인본·같은 채널로 다시 요청하면 **같은 요청을 돌려줍니다.** 설정이 하나라도 다르면 409로 막습니다. 중복 업로드를 만들지 않기 위한 것입니다.
- 요청이 들어가면 워커가 집어 갑니다. 여기서부터는 실제 업로드입니다.

## 4. 진행 확인

```bash
curl -sS http://localhost:18444/api/publications -H "Authorization: Bearer $TOKEN"
```

상태는 `pending` → `uploading` → `scheduled` → `published` 순서입니다.

- `scheduled`: 업로드가 끝나고 YouTube에 공개 예약이 걸린 상태입니다. 영상은 아직 비공개입니다.
- `published`: 예약 시각이 지나 YouTube가 공개로 바꾼 것을 워커가 확인한 상태입니다. 예약 시각 전에는 오지 않습니다.

업로드 뒤 예약까지는 YouTube 처리(`processingStatus: succeeded`)가 끝나야
합니다. 처리 중이면 워커가 다음 차례에 다시 시도합니다.

## 5. 문제가 생겼을 때

**임의로 상태를 되돌리거나 체크포인트를 지우지 마세요.** 중복 업로드의 가장
흔한 원인입니다.

| 증상 | 대처 |
|---|---|
| 실패(`failed`)로 멈춤 | `POST /publications/{id}/resume`. 같은 세션으로 이어 올립니다. |
| "업로드 세션 결과가 불명확합니다" (409) | 세션은 만들어졌는데 주소가 저장되기 전에 끊긴 경우입니다. **YouTube 채널에서 그 영상이 올라갔는지 눈으로 확인**한 뒤 수동 복구하세요. 그대로 재시도하면 영상이 두 개가 됩니다. |
| 예약 시각을 바꿔야 함 | `POST /publications/{id}/reschedule`. 업로드는 다시 하지 않습니다. |
| 승인본을 바꿔야 함 | 새 승인 → 새 게시 요청입니다. 기존 요청의 체크포인트를 재사용하지 마세요. 승인본이 다르면 어댑터가 막습니다. |

## 6. 실행 뒤 기록할 것

[인수인계](HANDOFF.md)에 남깁니다.

- 게시 요청 ID, 상태 전이 시각, 워커가 실제로 집었는지
- YouTube 처리 상태와 예약 시각(한국시간)
- 예상과 달랐던 것(할당량, 지연, 거절 사유)

**영상 링크와 채널 ID는 공개 저장소에 적지 않습니다.** `.runtime/` 아래
비공개 파일에만 둡니다.
