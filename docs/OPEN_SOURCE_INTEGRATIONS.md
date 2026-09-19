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
| charset-normalizer 3.5.1 | 들여오는 자막 파일의 인코딩 판별(CP949·EUC-KR 등) | [GitHub](https://github.com/jawah/charset_normalizer), MIT |
| Google Cloud Translate 3.20.2 | 공식 번역 SDK 어댑터 | [GitHub](https://github.com/googleapis/google-cloud-python/tree/main/packages/google-cloud-translate), Apache-2.0 |
| Google API Python Client 2.160.0 | YouTube 이어 올리기·공개 예약 어댑터 | [GitHub](https://github.com/googleapis/google-api-python-client), Apache-2.0 |
| google-auth-oauthlib 1.2.1 | 호출자가 YouTube OAuth 인증 클라이언트를 준비할 때 사용 | [GitHub](https://github.com/googleapis/google-auth-library-python-oauthlib), Apache-2.0 |

### 자막 정밀화 (`[subtitles]`)

| 프로젝트 | 도입 목적 | 라이선스 / 출처 |
|---|---|---|
| stable-ts 2.19.1 | 기존 대본을 오디오에 정렬(`align`), 자막 분할·병합(`split_by_length` 등), 단어 강조 ASS/SRT/VTT 출력 | [GitHub](https://github.com/jianfch/stable-ts), MIT |
| WhisperX 3.8.6 | wav2vec2 강제 정렬 기반 단어 타이밍, 화자 분리 | [GitHub](https://github.com/m-bain/whisperx), BSD-2-Clause |
| SpeechBrain 1.1.1 | 목소리 특징(ECAPA) 추출. 토큰 없는 화자 분리 공급자에 씁니다 | [GitHub](https://github.com/speechbrain/speechbrain), Apache-2.0 |
| kss 6.0.6 | 한국어 문장 분리. 자막 줄바꿈을 어절·문장 경계에 맞춤 | [GitHub](https://github.com/hyunwoongko/kss), BSD-3-Clause |
| ffsubsync 0.4.27 | 이미 있는 자막의 싱크를 원본 음성에 맞춰 보정 | [GitHub](https://github.com/smacke/ffsubsync), MIT |

ffsubsync는 **chardet(LGPL)** 과 **webrtcvad**를 의존성으로 끌어옵니다. chardet은 우리 코드가 부르지 않지만 `[subtitles]`를 설치한 워커 이미지에는 들어가므로 배포물 라이선스를 따질 때 함께 봅니다. webrtcvad는 C 확장인데 PyPI에 파이썬 3.11용 휠이 없어 워커 이미지가 설치 단계에서 컴파일합니다(`infra/Dockerfile.worker`가 그 층에서만 build-essential을 넣었다 지웁니다).

연결한 범위는 다음과 같습니다.

- stable-ts → `worker/analysis.py:align_text()`. `POST /source-assets/{id}/align`이 타이밍 없는 대본을 원본 음성에 맞춰 새 대본 버전을 만듭니다. 전사가 아니라 정렬이라 글자는 그대로 둡니다.
- WhisperX → `worker/analysis.py:diarize()`. `POST /source-assets/{id}/diarize`가 누가 언제 말했는지 찾아 최신 대본에 화자를 붙인 새 버전을 만듭니다. 배정은 `pipeline/speakers.py:assign_speakers()`가 겹친 시간으로 정합니다. `GET /source-assets/{id}/speakers`로 화자 목록을, `PUT /jobs/{id}/voice-assignments`로 화자별 음성을 저장합니다.
  - **Hugging Face 토큰이 필요합니다.** pyannote 화자 분리 모델은 게이트 모델이라 약관 동의 후 발급한 토큰을 `R4_HF_TOKEN`에 넣어야 합니다. 토큰이 없으면 모델을 내려받기 전에 막고 안내를 보여 줍니다. 모델 자체의 이용 조건은 whisperx의 BSD 라이선스와 별개입니다.
  - 검증 범위: 화자 배정 규칙과 작업 연결은 대역으로 테스트했고, 워커 이미지 안에서 `DiarizationPipeline` 진입점이 실제로 있는지 CI가 확인합니다. **실제 pyannote 추론 품질은 토큰이 필요해 아직 검증하지 못했습니다.**
- ffsubsync → `worker/analysis.py:sync_subtitles()`. `POST /source-assets/{id}/transcript/sync`가 최신 대본의 시각을 원본 음성에 맞춰 옮긴 새 버전을 만듭니다. 글자는 그대로 두고, 보정기가 맞추지 못했다고 하면 결과를 쓰지 않습니다. 아는 만큼 밀어 둔 자막이 돌아오는지와 이미 맞는 자막이 흔들리지 않는지를 `scripts/verify_sync.py`가 CI에서 잽니다.
- kss → `pipeline/subtitles.py:sentences()`. 자막을 나눌 때 문장 경계를 먼저 찾습니다. kss가 없으면 구두점 기준으로 내려갑니다.
- pysubs2 → `worker/rendering.py:write_subtitles()`(영상에 굽는 ASS)와 `pipeline/subtitle_files.py:subtitle_file()`(내려받는 SRT·WebVTT). 두 경로가 같은 `clip_cues()`·`apply_rules()`를 거치므로 파일 자막과 화면 자막의 시각·줄바꿈이 같습니다. 숏폼 편집본과 번역·더빙 작업 모두 이 함수를 씁니다. 작업 쪽에서 어느 자막이 구워졌는지는 `pipeline/workflow.py:rendered_cues()`가 정하고 렌더와 내보내기가 함께 씁니다.

검토한 뒤 채택하지 않은 후보도 남깁니다. [aeneas](https://github.com/readbeyond/aeneas)는 **AGPL v3**이라 네트워크 서비스 제공 시 서버 소스 공개 의무가 생깁니다. [ctc-forced-aligner](https://github.com/MahmoudAshraf97/ctc-forced-aligner)는 코드가 BSD이나 **기본 모델이 CC-BY-NC 4.0(비상업)** 입니다. 두 경우 모두 이 저장소의 사용 형태와 맞지 않아 제외했습니다.

### 자막 표시 규칙 기준

기본값에 근거가 없다는 문제를 남겨 두었습니다. 업계 표준으로 대신했습니다. 기준은 Netflix의 [Korean Timed Text Style Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/216001127-Korean-Timed-Text-Style-Guide)와 [General Requirements](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements)입니다.

지침은 I부(일반 번역 자막)와 II부(SDH, 청각장애인용)로 나뉘고 **읽기 속도 한도가 다릅니다**. 우리는 번역 자막을 만들므로 I부를 씁니다.

| 항목 | 지침 I부 (번역 자막) | 지침 II부 (SDH) | 이 저장소 기본값 |
|---|---|---|---|
| 줄당 글자 수 (I.2 / II.2) | 16자. 라틴 문자·공백·문장부호는 0.5자 | 동일 | 16자, 같은 계산 방식 |
| 줄 수 (I.11) | 최대 2줄. 글자 수 한도를 넘지 않는 한 한 줄로 유지 | 최대 2줄 | 2줄 |
| 읽기 속도 (I.15 / II.3) | 성인 **12자/초**, 아동 9자/초 | 성인 14자/초까지 상향 가능, 아동 11자/초 | **12자/초** |
| 최소 표시 시간 | 5/6초 | 5/6초 | 1초 (더 보수적) |
| 최대 표시 시간 | 7초 | 7초 | 7초 |

- 폭 계산은 `pipeline/subtitles.py:text_width()`입니다. `unicodedata.east_asian_width`가 `W`/`F`인 글자를 1자로, 나머지를 0.5자로 셉니다. 줄바꿈·분할·CPS 검사가 모두 이 값을 씁니다.
- **처음에 14자/초로 넣었다가 12자/초로 고쳤습니다.** 14는 SDH에서만 허용하는 상향값입니다. 검색 결과 스니펫만 보고 두 절을 구분하지 못한 오류였습니다.
- 지침은 OTT 번역 자막 기준이고 숏폼은 세로 화면·큰 글꼴이라 조건이 다릅니다. 그대로 최적값이라고 보지 않으며 다섯 값 모두 `R4_SUBTITLE_*` 설정으로 조정할 수 있습니다. 줄 길이의 화면 적정성은 아래 실측으로 확인했습니다.
- **반영하지 않은 규칙**: 지침의 줄 나눔(line treatment)은 구·절 단위로 끊으라고 합니다. 현재 구현은 문장 → 어절 → 글자 순서로만 끊고 한국어 절 경계는 판정하지 않습니다. 휴리스틱을 급히 넣기보다 한계로 남깁니다.
- 원문 페이지는 작업 환경의 이그레스 정책이 직접 접근을 막습니다. 검색 도구의 서버 측 조회로 본문(I.2/I.11/I.15, II.2/II.3)을 확인했습니다. 원문 자체를 브라우저로 연 것은 아닙니다.

### 실측 (CI, 워커 이미지 안)

- **자막 화면 측정** (`scripts/measure_subtitles.py`): 1080x1920 세로 화면에 libass로 한 프레임을 그리고 FFmpeg cropdetect로 글자 픽셀 상자를 잽니다. 기본 줄 길이 16자가 좌우 여백(각 50px, 쓸 수 있는 폭 980px) 안에 **한 줄로** 들어가야 통과합니다. 넘치면 libass가 제멋대로 다시 줄바꿈해 우리 줄 규칙이 화면에서 깨집니다. 실측값은 CI 로그의 `자막 화면 측정` 단계에 남습니다.
- **정렬 품질 검증** (`scripts/make_speech_sample.py` + `scripts/verify_align.py`): espeak-ng로 문장 사이에 1초 무음을 넣은 한국어 음성을 만들어 문장 시작 시각을 미리 확정한 뒤, 같은 대본을 타이밍 없이 넣고 stable-ts로 정렬해 오차를 잽니다. 글자가 바뀌거나 자막이 겹치거나 시작 오차가 1초를 넘으면 실패합니다. 모델을 실제로 내려받으므로 PR에 `verify-align` 라벨을 붙이거나 커밋 메시지에 `[verify-align]`을 넣을 때만 돌립니다. 합성 음성이라 사람 목소리보다 불리한 조건이며, 사람 목소리 품질을 대신하지는 않습니다.

#### 실측값 (2026-09-18, 워커 이미지, whisper tiny, espeak-ng 합성 음성)

- 화면 1080x1920, 글자 크기 64, 좌우 여백 각 50px(쓸 수 있는 폭 980px) 기준 렌더 폭:

  | 한글 글자 수 | 8 | 10 | 12 | 14 | **16** | 18 | 20 |
  |---|---|---|---|---|---|---|---|
  | 렌더 폭 | 322px | 403px | 485px | 566px | **647px** | 728px | 810px |
  | 화면 대비 | 30% | 37% | 45% | 52% | **60%** | 67% | 75% |

  기본 줄 길이 16자는 647px로 여백 안에 한 줄로 들어갑니다(한 줄 높이 41px). 이 글자 크기에서는 24자까지 들어가므로(26자는 1054px로 넘음) 16자 기본값에 여유가 있습니다.
- 정렬 오차(whisper small, espeak 합성 음성): 자막 1 **0.01초**, 자막 2 **0.05초**, 자막 3 **0.02초**. 문장 경계 3/3개가 자막 경계로 남습니다. 여기까지 오는 데 세 가지를 고쳤습니다.
  - 자막 시각은 정렬기 옵션이 아니라 우리가 만듭니다. 정렬은 한 덩어리로 돌려 단어 시각을 받고, `pipeline/alignment.py:cues_for_lines()`가 대본의 줄마다 자막을 만듭니다. 정렬기의 줄 유지 옵션(`original_split`)은 첫 자막을 **1.00초 늦추므로** 쓰지 않습니다(측정: 옵션 켬 2.00초, 끔 0.98초, 실제 1.00초). 무음 보정과 VAD는 이 지연에 영향이 없었습니다.
  - 단어 시각은 무음 안쪽으로 당겨지기도 합니다(측정: 마지막 문장이 1.73초 이르게 시작, tiny·small 모두). 모델을 키워도 같아서 결과를 다듬습니다. `snap_starts()`가 자막 시작을 가까운 발화 시작(FFmpeg silencedetect)으로 맞춰 무음에서 자막이 먼저 뜨는 것을 막습니다(1.73초 → 0.00초). 앞 자막을 침범하거나 자막이 사라질 만큼 옮겨야 하면 그대로 둡니다.
  - VAD 기본값 두 개를 껐습니다. `speech_pad_ms`(기본 400ms)는 발화 앞뒤에 여유를 붙여 자막을 그만큼 일찍 시작시키고, `min_silence_duration_ms`(기본 2000ms)는 2초보다 짧은 무음을 발화 경계로 보지 않습니다. 후자를 그대로 두면 문장 사이 1초 쉼이 무시돼 **18초 음성 전체가 발화 구간 하나**로 잡히고, 맞출 시작점이 없어 자막이 밀린 채 남습니다(측정: 자막 2 1.57초, 자막 3 1.71초). 200ms로 낮춰 문장마다 끊고, 문장 안에서 잘게 끊긴 조각은 `merge_spans()`가 0.3초 기준으로 다시 합칩니다.
  - 설정은 `supported_options()`가 이름별로 걸러서 넘깁니다. `TypeError`를 통째로 잡으면 설정이 하나도 안 걸린 채 기본값으로 돌아가는데, 위 문제가 그 경로에 가려져 있었습니다.
  - 검증은 운영 기본값과 같은 `small` 모델로 돕니다. `tiny`로 재면 쓰지도 않는 모델의 오차를 재게 됩니다.
- 처음 측정에서 3번 문장 오차가 5.79초로 나왔는데, 정렬 문제가 아니라 대본을 한 줄로 넘겨 2·3번 문장이 한 자막으로 합쳐진 탓이었습니다. 대본에 줄바꿈이 있으면 그 줄을 자막 경계로 유지하도록 `align_text()`를 고쳤습니다(`original_split`).

#### 사람 목소리와 실제 화자 분리

- **사람 목소리 정렬 검증**: `scripts/fetch_korean_speech.py`가 Hugging Face datasets-server에서 공개 한국어 낭독 음성을 몇 조각 받아 합성 음성과 같은 형식으로 묶습니다. CI가 같은 검사를 한 번 더 돌립니다. 받지 못하면 실패합니다. 검증을 건너뛴 것과 통과한 것은 구분해야 합니다.
  - **첫 측정에서 합성 음성과 차이가 드러났습니다.** 합성 음성 최대 오차 0.01초, 사람 목소리 **1.57초**. 원인은 발화 시작을 FFmpeg 무음 감지로 찾은 것이었습니다. 실제 녹음은 배경 잡음이 있어 무음이 잡히지 않고, 그래서 자막 시작을 다듬지 못했습니다. 합성 음성은 완전한 디지털 무음이라 이 문제가 보이지 않았습니다.
  - 지금은 Silero VAD(faster-whisper 내장)로 발화 구간을 찾고, 못 쓰면 무음 감지로 내려갑니다. 새 의존성은 없습니다. 기본값 조정은 위 합성 음성 항목과 같습니다(여유 0ms, 무음 기준 200ms).
  - 자막 시작을 맞추는 규칙: 앞 자막이 끝나기 전에 시작한 발화는 앞 자막의 몫이라 빼고, 남은 발화의 시작 중 가장 가까운 것으로 맞춥니다. 2초를 넘게 움직여야 하거나 자막이 사라질 만큼 뒤로 가면 그대로 둡니다.
  - **정답 시각을 만드는 쪽에서도 문제가 나왔습니다.** 조각의 앞 무음을 -40dB 고정 문턱으로 쟀는데, 이 녹음은 말이 없는 구간의 실내 잡음이 그보다 큽니다. 그래서 잡음이 시작된 지점을 말이 시작된 지점으로 적었습니다(2번 조각: 앞 무음 0.08초로 기록, 실제 말은 1.65초 뒤). 지금은 조각마다 그 파일의 최대 음량에서 35dB 아래로 문턱을 다시 잡고, 고정 문턱으로 잰 값도 `expected.json`과 로그에 함께 남깁니다. 정답이 문턱 때문에 얼마나 움직였는지 보이지 않으면 검증이 통과해도 무엇을 통과한 것인지 알 수 없습니다. 실제로 움직인 값은 세 조각 중 하나뿐이었습니다(0.08 → 1.65초, 나머지 둘은 그대로).
  - 사람 목소리 정렬 오차(whisper small, zeroth-korean 3문장): 자막 1 **0.77초**, 자막 2 **0.08초**, 자막 3 **0.07초**. 문장 경계 3/3개가 자막 경계로 남습니다.
  - **이 수치의 한계**: 이 데이터셋에는 단어 시각 정답이 없습니다. "실제 시작"은 우리가 에너지로 재는 값이고, 자막 시작은 Silero VAD가 찾는 값입니다. 둘은 서로 다른 방법이라 값이 맞아떨어지는 것은 교차 확인이 되지만, 외부 정답으로 잰 정확도는 아닙니다. 남은 0.77초도 정렬이 늦은 것인지 정답이 이른 것인지 이 방법으로는 가리지 못합니다. 단어 시각이 있는 한국어 공개 데이터가 필요합니다.
- **화자 분리 실검증**: `scripts/verify_diarize.py`가 목소리 둘인 음성에 pyannote를 실제로 돌려 화자가 갈리는지 확인합니다. 정답 화자별로 분리 결과가 한 표시로 몰리는지 봅니다. 표시 이름은 공급자가 정하므로 이름이 아니라 묶임만 봅니다.
  - **토큰 없는 공급자도 있습니다.** `analysis.diarize_by_embedding()`은 공개 목소리 특징 모델(`speechbrain/spkrec-ecapa-voxceleb`)로 같은 일을 합니다. 발화 구간을 VAD로 찾고 겹치는 창으로 잘라 창마다 특징을 뽑은 뒤 코사인 거리로 묶습니다. 묶기·배정 규칙은 `pipeline/speakers.py`의 순수 계산이라 테스트로 고정했습니다. CI가 이 공급자로 화자 분리를 **시크릿 없이 매번** 검증합니다.
  - 실측(CI `1bff963`, 30.17초 음성, 두 목소리 번갈아 4조각): 화자 구간 4개를 찾았고 문장 4개 모두 정답 화자와 맞는 표시를 받았습니다(A→SPEAKER_00, B→SPEAKER_01). 구간 시작은 정답과 0.03~0.78초 차이, 끝은 1.2~1.5초 이르게 끝납니다(말끝 잔향이 정답 끝을 늦추는 것으로, 자막 끝 시각에서 본 것과 같은 현상입니다).
  - **그것이 통과해도 pyannote가 검증된 것은 아닙니다.** 둘은 다른 모델입니다. 토큰 없는 공급자는 겹쳐 말하는 구간을 다루지 못하고 화자 수를 스스로 세지 않습니다(`speakers`로 알려 줘야 합니다). 목소리가 비슷하면 갈리지 않습니다. 그래서 기본 공급자가 아니라 선택지입니다.
  - **동의해야 하는 모델 페이지는 버전이 정합니다.** 실측(CI `a18fd3d`): 설치된 whisperx는 `pyannote/speaker-diarization-community-1`을 받으러 갑니다. `speaker-diarization-3.1`에서만 동의하면 같은 증상이 계속됩니다. 코드가 실행 시점에 모델 이름을 찾아 안내에 넣고, CI가 그 이름을 찍습니다.
  - **pyannote 실검증에는 저장소 시크릿 `HF_TOKEN`이 있어야 합니다.** pyannote 화자 분리 모델은 게이트 모델이라 [약관 동의](https://huggingface.co/pyannote/speaker-diarization-3.1)를 마친 계정의 토큰이 필요합니다. 시크릿이 없으면 이 단계는 건너뜁니다.
  - 운영에서도 같은 값을 `R4_HF_TOKEN`으로 넣습니다.

### 검토했으나 추가하지 않은 자막 도구

- silero-vad (MIT): 별도로 설치하지 않았습니다. faster-whisper가 Silero VAD를 내장하고 있고 `analysis.py:transcribe()`가 `vad_filter=True`로 이미 사용합니다.
- [subaligner](https://github.com/baxtree/subaligner), NeMo Forced Aligner: 정렬 품질은 좋으나 TensorFlow/NeMo를 통째로 끌어옵니다. 이미 CPU 전용 휠로 설치량을 줄인 결정과 어긋납니다.
- `srt`, `webvtt-py`: pysubs2가 SRT·WebVTT·ASS를 모두 처리하므로 중복입니다. 내보내기도 pysubs2로 구현했습니다(`pipeline/subtitle_files.py`).
- [Subtitle Edit](https://github.com/SubtitleEdit/subtitleedit) (GPL, C#): 의존성으로 쓸 수 없습니다. CPS 계산과 줄 분배 규칙은 참고 자료로만 봅니다.

조회한 주요 라이선스 사본은 [third_party/licenses](../third_party/licenses)에 보관합니다. 설치 패키지의 라이선스·NOTICE도 그대로 유지합니다. FFmpeg는 빌드 옵션에 따라 조건이 달라지므로 실제 배포 바이너리와 소스 제공 조건을 확인해야 합니다. Python 라이브러리의 라이선스가 모델 가중치·API 서비스 약관까지 대체하지는 않습니다.

## 실제로 연결한 기능

- `/clips`: 구간·화면·자막·제목을 검증하고 불변 편집본 및 렌더 요청 생성.
- `media.run` → Celery 워커: S3 다운로드 → 로컬 처리 → 결과 업로드 → DB 결과물 등록.
- `/source-assets/{id}/analyze`: 로컬 STT 또는 장면 감지. 분석 의존성 설치가 필요하며 STT 첫 실행은 모델을 다운로드할 수 있습니다.
- `/source-assets/{id}/transcript/sync`: 들인 자막이 원본과 어긋날 때 ffsubsync로 시각을 통째로 옮긴 새 대본 버전을 만듭니다. 글자는 건드리지 않고, 얼마나 옮겼는지(`offset_seconds`)를 작업 결과에 남깁니다.
- `/source-assets/{id}/transcript/import`: 밖에서 만든 SRT·WebVTT·ASS 파일을 대본 새 버전으로 들입니다. 형식은 pysubs2가 글자를 보고 판별하고, 꾸밈 표기는 벗깁니다. 시각은 파일에 적힌 그대로 씁니다. 인코딩은 BOM → UTF-8 → charset-normalizer 순으로 정하고, 판별기가 고른 경우에는 무엇으로 읽었는지(`encoding`, `encoding_detected`)와 다른 후보를 함께 돌려주어 화면에서 되돌릴 수 있게 합니다. 판별기까지 실패하면 후보별 미리보기를 주어 사람이 고릅니다.
- YouTube 자막 트랙: 게시할 때 같은 자막을 `captions.insert`로 올립니다(`R4_YOUTUBE_CAPTIONS_ENABLED`, 기본 꺼짐). 같은 언어 트랙이 이미 있으면 올리지 않고, 실패해도 게시를 막지 않습니다.
- `/subtitle-templates`, `/clips`의 `subtitle_template`: 영상에 굽는 자막 모양(글꼴·색·외곽선·위치)을 내장 템플릿 이름으로 고릅니다. 구현은 `pipeline/subtitle_templates.py`이며 pysubs2 스타일로 바꿔 렌더의 ASS에 넣습니다. 같은 템플릿을 파일에 적용하는 명령줄은 [자막 파일·템플릿 도구](SUBTITLE_TOOL.md)입니다.
- `/clips/{id}/subtitles?format=srt|vtt`, `/jobs/{id}/subtitles?format=srt|vtt`: 숏폼 편집본과 번역·더빙 작업의 자막을 SRT·WebVTT 파일로 내려받습니다. 생성은 `pipeline/subtitle_files.py:subtitle_file()`이며 pysubs2가 형식을 씁니다. 저장하지 않고 요청할 때 만듭니다.

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
- STT 실제 추론을 CI에서 잽니다(사람 목소리, whisper small): 전체 CER **9.7%**. 실제 공급자 응답, OAuth 및 업로드는 아직 미검증.
- DB 마이그레이션 업그레이드·다운그레이드·재업그레이드 통과(SQLite).
- 관리화면 타입 검사·빌드 및 브라우저 로그인·원본 미리보기·구간 입력·렌더 요청 확인. 브라우저 검증은 테스트 DB와 로컬 미디어 대역을 사용함.
- Compose 전체 기동과 실제 S3/MinIO 연결을 CI에서 확인합니다(`스택 기동 검증` 잡). 운영 구성(`compose.runtime.yml`) 9개 컨테이너를 띄우고 `scripts/smoke.py`로 전 경로를 한 번 돌립니다.

## 남은 제품 기능

LLM 하이라이트 추천, 자동 얼굴 추적, 다중 구간 조합, 정교한 타임라인 UI, 단어별 자막 강조, 프리뷰 전용 저해상도 렌더, 정교한 오디오 믹싱은 별도 구현 대상입니다. 단계별 더빙·게시 연결은 [후속 구현](CONNECTED_WORKFLOW.md)을 참고하세요.
