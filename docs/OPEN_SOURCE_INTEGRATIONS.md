# 오픈소스 통합 현황

2026-09-18 사용자 요청에 따라 GitHub 프로젝트를 조사하고 기존 코드에 필요한 라이브러리와 연결 코드를 추가했습니다. 외부 저장소 전체를 복사하거나 하위 Git 저장소를 포함하지 않고 정식 패키지를 버전 고정해 사용합니다. 직접 작성한 연결 코드는 이 저장소에서 관리합니다.

## 선택한 프로젝트

| 프로젝트 | 통합 | 라이선스 / 출처 |
|---|---|---|
| FFmpeg | 컷 편집, 크롭·패딩, H.264/AAC 인코딩, 자막·제목 합성 | [소스](https://github.com/FFmpeg/FFmpeg), [빌드별 LGPL/GPL 안내](https://ffmpeg.org/legal.html) |
| faster-whisper 1.2.1 | 로컬 음성 인식, 원본 시각 대본 생성 | [GitHub](https://github.com/SYSTRAN/faster-whisper), MIT |
| PySceneDetect 0.6.7.1 | 장면 경계 감지, 관리화면의 구간 선택 | [GitHub](https://github.com/Breakthrough/PySceneDetect), BSD-3-Clause |
| pysubs2 1.8.0 | 자막 타임라인, ASS 생성, 화면 제목 스타일 | [GitHub](https://github.com/tkarabela/pysubs2), MIT |
| Google Cloud Translate 3.20.2 | 공식 번역 SDK 어댑터 | [GitHub](https://github.com/googleapis/google-cloud-python/tree/main/packages/google-cloud-translate), Apache-2.0 |
| Google API Python Client 2.160.0 | YouTube 이어 올리기·공개 예약 어댑터 | [GitHub](https://github.com/googleapis/google-api-python-client), Apache-2.0 |
| google-auth-oauthlib 1.2.1 | 호출자가 YouTube OAuth 인증 클라이언트를 준비할 때 사용 | [GitHub](https://github.com/googleapis/google-auth-library-python-oauthlib), Apache-2.0 |

조회한 주요 라이선스 사본은 [third_party/licenses](../third_party/licenses)에 보관합니다. 설치 패키지의 라이선스·NOTICE도 그대로 유지합니다. FFmpeg는 빌드 옵션에 따라 조건이 달라지므로 실제 배포 바이너리와 소스 제공 조건을 확인해야 합니다. Python 라이브러리의 라이선스가 모델 가중치·API 서비스 약관까지 대체하지는 않습니다.

## 실제로 연결한 기능

- `/clips`: 구간·화면·자막·제목을 검증하고 불변 편집본 및 렌더 요청 생성.
- `media.run` → Celery 워커: S3 다운로드 → 로컬 처리 → 결과 업로드 → DB 결과물 등록.
- `/source-assets/{id}/analyze`: 로컬 STT 또는 장면 감지. 분석 의존성 설치가 필요하며 STT 첫 실행은 모델을 다운로드할 수 있습니다.
- 대본 가져오기·새 버전 저장, 문장 경계 기반 구간 후보. 현재 후보 알고리즘은 오프라인 규칙 기반이며 LLM이나 조회수 예측 기능이 아닙니다.
- 관리화면: 영상 재생, 구간·세로 구도·자막·제목 편집, 렌더 상태, 결과 재생·다운로드, 버전별 승인.
- 명령행: `python -m worker.cli`로 DB·S3 없이 로컬 파일 처리.
- 오류 및 중복 처리: 작업 원자적 점유, 동일 메시지 재전달 무시, 실패 재시도, 오래된 실행 회수 시도. 실행 제한은 1시간, 정체 작업 재시도는 2시간 이후입니다.

## 어댑터까지 구현한 기능

`services/worker/worker/providers.py`의 GoogleTranslator, ElevenLabsSpeech, SyncLipsync와 `youtube.py`의 upload_approved/schedule_video는 호출 가능한 연결 코드입니다. 기본적으로 유료 호출·업로드를 비활성화하고 테스트는 가짜 공급자 응답을 사용합니다.

**이 어댑터들이 관리화면의 원클릭 전체 번역·더빙·립싱크·게시 흐름으로 연결된 것은 아닙니다.** 다음 통합 작업은 예산 예약·정산과 각 단계 실행 연결, 음성 길이 조정·배경음 처리, OAuth 연결 화면, publication DB 체크포인트 저장, 채널 확인 및 예약 결과 재조회입니다. 기존 `job.start`도 아직 이 어댑터와 연결되지 않았습니다. 이를 완료했다고 표시하지 않습니다.

YouTube 어댑터는 승인 식별자와 명시적 실행 설정을 받고 비공개 업로드합니다. 호출자는 승인된 파일·체크섬을 검증하고 체크포인트를 DB에 저장해야 합니다. 응답 유실 시 기존 세션을 조회하며 세션 생성 결과조차 불명확하면 중복 업로드 대신 수동 확인을 요구합니다. 예약 전 YouTube 처리 완료와 비공개 상태를 확인합니다. SDK의 `_in_error_state`를 사용하므로 SDK 버전 변경 시 재개 계약 테스트를 다시 실행합니다.

유료 공급자의 제출·조회는 분리되어 있으며 네트워크 오류를 자동 재제출로 처리하지 않습니다. 자격증명, 예산값, 채널은 사용자의 실제 설정으로 연결해야 합니다. 이번 작업에서 유료 호출·실제 영상 업로드는 실행하지 않았습니다.

## 실행

저장소 루트에서 Python 3.11 또는 3.12와 FFmpeg(subtitles 필터 포함)를 준비합니다. 한국어 자막에는 Noto Sans CJK KR 글꼴이 필요합니다. Docker 워커는 FFmpeg와 글꼴을 설치합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,analysis,providers]'
export PYTHONPATH=packages/pipeline:services/api:services/worker
python -m worker.cli --help
python -m worker.cli render /path/to/long.mp4 examples/clip.json /path/to/short.mp4
python -m worker.cli transcribe /path/to/long.mp4 /path/to/transcript.json --model small --language ko
python -m worker.cli scenes /path/to/long.mp4 /path/to/scenes.json
python -m worker.cli suggest /path/to/transcript.json /path/to/candidates.json --duration 600
```

`examples/clip.json`은 10~40초 구간 예시입니다. 원본 길이에 맞게 수정합니다. 로컬 명령은 전체 DB·예산·승인 흐름을 사용하지 않는 파일 도구입니다. 실행 결과는 Git에 커밋하지 않습니다.

웹·워커 실행은 [개발 환경](DEVELOPMENT.md)을 따릅니다. 기존 DB에는 `alembic upgrade head`로 `0002_media_tasks`를 적용합니다. Docker를 사용하면 새 워커 이미지를 빌드해야 합니다. `R4_S3_ENDPOINT_URL`은 서버 내부 접속 주소, `R4_S3_PUBLIC_ENDPOINT_URL`은 브라우저가 접근할 수 있는 서명 URL 주소입니다. 서명 후 호스트를 바꾸면 서명이 깨지므로 별도 클라이언트로 발급합니다.

## 검증 범위

- 기존 테스트 포함 Python 138개 통과, PostgreSQL 전용 경합 테스트 1개는 로컬에서 건너뜀.
- 실제 FFmpeg 테스트 영상 생성·크롭/패딩·자막 합성·디코딩·음성 에너지 검사 통과.
- PySceneDetect로 실제 합성 영상의 장면 구간 확인.
- STT 및 Google SDK 설치·불러오기 확인. 실제 STT 모델 추론, 실제 공급자 응답, OAuth 및 업로드는 아직 미검증.
- DB 마이그레이션 업그레이드·다운그레이드·재업그레이드 통과(SQLite).
- 관리화면 타입 검사·빌드 및 브라우저 로그인·원본 미리보기·구간 입력·렌더 요청 확인. 브라우저 검증은 테스트 DB와 로컬 미디어 대역을 사용함.
- Docker 데몬이 없어 Compose 전체 기동과 실제 S3/MinIO 연결은 미검증.

## 남은 제품 기능

LLM 하이라이트 추천, 자동 얼굴 추적, 다중 구간 조합, 정교한 타임라인 UI, 단어별 자막 강조, 프리뷰 전용 저해상도 렌더, 전체 유료 파이프라인·게시 UI 연결은 별도 구현 대상입니다. 현재 편집기는 원어 음성을 유지합니다.
