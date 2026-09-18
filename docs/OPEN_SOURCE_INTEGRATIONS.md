> 후속 상태: 공급자 어댑터는 이제 [단계별 제작·게시](CONNECTED_WORKFLOW.md)에 연결되어 있습니다. 아래 초기 검증 기록과 구분하세요.

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

### 자막 정밀화 (`[subtitles]`)

| 프로젝트 | 도입 목적 | 라이선스 / 출처 |
|---|---|---|
| stable-ts 2.19.1 | 기존 대본을 오디오에 정렬(`align`), 자막 분할·병합(`split_by_length` 등), 단어 강조 ASS/SRT/VTT 출력 | [GitHub](https://github.com/jianfch/stable-ts), MIT |
| WhisperX 3.8.6 | wav2vec2 강제 정렬 기반 단어 타이밍, 화자 분리 | [GitHub](https://github.com/m-bain/whisperx), BSD-2-Clause |
| kss 6.0.6 | 한국어 문장 분리. 자막 줄바꿈을 어절·문장 경계에 맞춤 | [GitHub](https://github.com/hyunwoongko/kss), BSD-3-Clause |

연결한 범위는 다음과 같습니다. **WhisperX는 아직 코드에서 쓰지 않습니다**(화자 분리용으로 등록만 했습니다).

- stable-ts → `worker/analysis.py:align_text()`. `POST /source-assets/{id}/align`이 타이밍 없는 대본을 원본 음성에 맞춰 새 대본 버전을 만듭니다. 전사가 아니라 정렬이라 글자는 그대로 둡니다.
- kss → `pipeline/subtitles.py:sentences()`. 자막을 나눌 때 문장 경계를 먼저 찾습니다. kss가 없으면 구두점 기준으로 내려갑니다.

검토한 뒤 채택하지 않은 후보도 남깁니다. [aeneas](https://github.com/readbeyond/aeneas)는 **AGPL v3**이라 네트워크 서비스 제공 시 서버 소스 공개 의무가 생깁니다. [ctc-forced-aligner](https://github.com/MahmoudAshraf97/ctc-forced-aligner)는 코드가 BSD이나 **기본 모델이 CC-BY-NC 4.0(비상업)** 입니다. 두 경우 모두 이 저장소의 사용 형태와 맞지 않아 제외했습니다.

### 자막 표시 규칙 기준

기본값에 근거가 없다는 문제를 남겨 두었습니다. 업계 표준으로 대신했습니다. 기준은 Netflix의 [Korean Timed Text Style Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/216001127-Korean-Timed-Text-Style-Guide)와 [General Requirements](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements)입니다.

| 항목 | 지침 | 이 저장소 기본값 |
|---|---|---|
| 줄당 글자 수 | 16자. 라틴 문자·공백·문장부호는 0.5자로 계산 | 16자, 같은 계산 방식 |
| 줄 수 | 대사 2줄 | 2줄 |
| 읽기 속도 | 성인물 초당 14자, 아동물 11자 | 14자 |
| 최소 표시 시간 | 5/6초 | 1초 (더 보수적) |
| 최대 표시 시간 | 7초 | 7초 |

- 폭 계산은 `pipeline/subtitles.py:text_width()`입니다. `unicodedata.east_asian_width`가 `W`/`F`인 글자를 1자로, 나머지를 0.5자로 셉니다. 줄바꿈·분할·CPS 검사가 모두 이 값을 씁니다.
- 지침은 OTT 번역 자막 기준이고 숏폼은 세로 화면·큰 글꼴이라 조건이 다릅니다. 그대로 최적값이라고 보지 않으며 다섯 값 모두 `R4_SUBTITLE_*` 설정으로 조정할 수 있습니다.
- **반영하지 않은 규칙**: 지침의 줄 나눔(line treatment)은 구·절 단위로 끊으라고 합니다. 현재 구현은 문장 → 어절 → 글자 순서로만 끊고 한국어 절 경계는 판정하지 않습니다. 휴리스틱을 급히 넣기보다 한계로 남깁니다.
- 원문 페이지는 작업 환경의 이그레스 정책이 막고 있어 검색 결과 스니펫으로 확인했습니다. 값을 바꾸기 전에 원문을 직접 확인하십시오.

### 검토했으나 추가하지 않은 자막 도구

- [ffsubsync](https://github.com/smacke/ffsubsync) (MIT): 이미 있는 자막 파일의 싱크를 오디오로 보정합니다. 지금은 자막을 우리가 만들어 쓸 자리가 없습니다. 외부 SRT 반입 경로가 생기면 그때가 적기입니다.
- silero-vad (MIT): 별도로 설치하지 않았습니다. faster-whisper가 Silero VAD를 내장하고 있고 `analysis.py:transcribe()`가 `vad_filter=True`로 이미 사용합니다.
- [subaligner](https://github.com/baxtree/subaligner), NeMo Forced Aligner: 정렬 품질은 좋으나 TensorFlow/NeMo를 통째로 끌어옵니다. 이미 CPU 전용 휠로 설치량을 줄인 결정과 어긋납니다.
- `srt`, `webvtt-py`: pysubs2가 SRT·WebVTT·ASS를 모두 처리하므로 중복입니다.
- [Subtitle Edit](https://github.com/SubtitleEdit/subtitleedit) (GPL, C#): 의존성으로 쓸 수 없습니다. CPS 계산과 줄 분배 규칙은 참고 자료로만 봅니다.

조회한 주요 라이선스 사본은 [third_party/licenses](../third_party/licenses)에 보관합니다. 설치 패키지의 라이선스·NOTICE도 그대로 유지합니다. FFmpeg는 빌드 옵션에 따라 조건이 달라지므로 실제 배포 바이너리와 소스 제공 조건을 확인해야 합니다. Python 라이브러리의 라이선스가 모델 가중치·API 서비스 약관까지 대체하지는 않습니다.

## 실제로 연결한 기능

- `/clips`: 구간·화면·자막·제목을 검증하고 불변 편집본 및 렌더 요청 생성.
- `media.run` → Celery 워커: S3 다운로드 → 로컬 처리 → 결과 업로드 → DB 결과물 등록.
- `/source-assets/{id}/analyze`: 로컬 STT 또는 장면 감지. 분석 의존성 설치가 필요하며 STT 첫 실행은 모델을 다운로드할 수 있습니다.

## `[subtitles]` 설치 방법

`stable-ts`와 `whisperx`가 PyTorch를 끌어옵니다. 기본 인덱스는 리눅스에서 CUDA 휠을 함께 설치하므로 설치량이 큽니다.

```bash
# CPU만 사용하는 경우: torch를 CPU 빌드로 먼저 설치한 뒤 extra를 설치합니다.
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e '.[analysis,subtitles]'

# GPU를 사용하는 경우: 기본 인덱스 그대로 설치합니다.
pip install -e '.[analysis,subtitles]'
```

현재 설정 기본값은 `R4_WHISPER_DEVICE=cpu`이고 Docker Desktop for Mac은 NVIDIA GPU를 전달하지 못하므로, 그 환경에서는 CPU 빌드가 맞습니다.

`infra/Dockerfile.worker`는 CPU 전용 PyTorch를 먼저 고정한 뒤 `[analysis,providers,imports,subtitles]`를 설치합니다. 기본 인덱스로 받으면 CUDA 휠이 함께 들어와 약 5GB가 늘어납니다(측정: nvidia 4.39GB + triton 0.57GB). GPU 워커가 필요하면 CPU 단계를 지우고 기본 인덱스로 설치한 뒤 `R4_WHISPER_DEVICE`를 바꿉니다.

Dockerfile의 torch 버전은 whisperx가 요구하는 범위(`torch~=2.8.0`, `torchaudio~=2.8.0`, `torchvision~=0.23.0`)와 맞춰야 합니다. whisperx를 올릴 때 함께 고쳐야 하며, 맞지 않으면 빌드가 의존성 충돌로 실패합니다.

### 설치 검증 (2026-09-18, 리눅스 x86-64 / Python 3.11)

- `pip install '.[analysis,subtitles]'` 성공, `pip check` 이상 없음.
- 프로젝트 고정값이 모두 유지됨: SQLAlchemy 2.0.36, alembic 1.14.0, faster-whisper 1.2.1, httpx 0.28.1, pysubs2 1.8.0.
- 앱 모듈(`adminapi.main`, `worker.workflow_tasks`, `worker.rendering`)과 신규 라이브러리를 같은 인터프리터에서 동시 임포트 확인.
- kss 한국어 문장 분리 실행 확인. mecab(`python-mecab-ko`)이 없으면 휴리스틱으로 동작하며 정확도가 떨어집니다.
- **설치량 8.4GB**(기본 인덱스). 이 중 nvidia CUDA 휠이 대부분입니다.
- whisperx가 torch를 2.8.0으로 고정합니다. stable-ts 단독 설치 시의 2.14.0보다 낮으므로 한쪽을 올릴 때 확인이 필요합니다.
- whisperx가 optuna를 통해 alembic·sqlalchemy를 요구하지만 하한 조건(`>=`)이라 프로젝트 고정값과 충돌하지 않습니다.
- CPU 전용 설치 경로와 워커 이미지 빌드는 **CI에서 검증했습니다**(2026-09-18, GitHub Actions `워커 이미지 빌드` 잡). 작업 환경에는 Docker 데몬이 없고 `download.pytorch.org`가 차단되어 직접 돌릴 수 없어 CI가 대신합니다.
  - 워커 이미지 **4.66GB**, API 이미지 256MB. 빌드 시간 약 3분.
  - 컨테이너 안에서 `torch 2.8.0+cpu` 확인. CUDA 휠로 되돌아가면 잡이 실패합니다.
  - 워커 모듈과 stable-ts·whisperx·kss·pysubs2·faster-whisper 임포트 확인. 모델은 내려받지 않습니다.
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

웹·워커 실행은 [개발 환경](DEVELOPMENT.md)을 따릅니다. 기존 DB에는 `alembic upgrade head`로 `0003_workflow`를 적용합니다. Docker를 사용하면 새 워커 이미지를 빌드해야 합니다. `R4_S3_ENDPOINT_URL`은 서버 내부 접속 주소, `R4_S3_PUBLIC_ENDPOINT_URL`은 브라우저가 접근할 수 있는 서명 URL 주소입니다. 서명 후 호스트를 바꾸면 서명이 깨지므로 별도 클라이언트로 발급합니다.

## 검증 범위

- 기존 테스트 포함 Python 138개 통과, PostgreSQL 전용 경합 테스트 1개는 로컬에서 건너뜀.
- 실제 FFmpeg 테스트 영상 생성·크롭/패딩·자막 합성·디코딩·음성 에너지 검사 통과.
- PySceneDetect로 실제 합성 영상의 장면 구간 확인.
- STT 및 Google SDK 설치·불러오기 확인. 실제 STT 모델 추론, 실제 공급자 응답, OAuth 및 업로드는 아직 미검증.
- DB 마이그레이션 업그레이드·다운그레이드·재업그레이드 통과(SQLite).
- 관리화면 타입 검사·빌드 및 브라우저 로그인·원본 미리보기·구간 입력·렌더 요청 확인. 브라우저 검증은 테스트 DB와 로컬 미디어 대역을 사용함.
- Docker 데몬이 없어 Compose 전체 기동과 실제 S3/MinIO 연결은 미검증.

## 남은 제품 기능

LLM 하이라이트 추천, 자동 얼굴 추적, 다중 구간 조합, 정교한 타임라인 UI, 단어별 자막 강조, 프리뷰 전용 저해상도 렌더, 정교한 오디오 믹싱은 별도 구현 대상입니다. 단계별 더빙·게시 연결은 [후속 구현](CONNECTED_WORKFLOW.md)을 참고하세요.
