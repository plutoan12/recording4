# 자막 파일·템플릿 도구

자막 파일(SRT·WebVTT·ASS)을 검사·변환·다듬고, 자막 템플릿(글꼴·색·외곽선·위치)을 골라 ASS 파일이나 영상에 굽는 명령줄 도구입니다. DB·큐·유료 API 없이 파일만 다룹니다. 서버의 편집기·렌더와 **같은 코드**(`pipeline.subtitle_files`, `pipeline.subtitles`, `pipeline.subtitle_templates`)를 쓰므로 여기서 확인한 결과가 서버 렌더와 같습니다.

## 실행

```bash
pip install -e ".[dev]"          # 설치하면 r4-subtitles 명령이 생깁니다
r4-subtitles --help
python -m pipeline.subtitle_tool --help   # 같은 도구
```

`burn`만 FFmpeg(`ffmpeg`, `ffprobe`)와 한국어 글꼴이 필요합니다. 워커 Docker 이미지에는 들어 있습니다. 경로는 `R4_FFMPEG_BINARY`, `R4_FFPROBE_BINARY`로 줄 수 있습니다.

## 명령

| 명령 | 하는 일 | 종료 코드 |
|---|---|---|
| `info FILE` | 인코딩, 자막 수, 구간, 규칙 위반 수 요약 | 0 |
| `check FILE [--json]` | 표시 규칙 위반을 자막 번호별로 보고. 글자는 고치지 않음 | 위반 있으면 1 |
| `convert IN OUT` | SRT·VTT·ASS → SRT 또는 VTT. 글자·시각 그대로, 꾸밈 표기만 벗김 | 0 |
| `shape IN OUT` | 줄바꿈·분할 규칙을 적용해 저장. 서버가 굽는 자막과 같은 결과 | 0 |
| `shift IN OUT --offset 초` | 시각 이동. 0초 앞으로 나간 자막은 자르고 다 나간 자막은 뺌 | 0 |
| `cut IN OUT --start 초 --end 초` | 구간만 남기고 구간 시작을 0초로 | 0 |
| `templates list` / `show 이름` / `export 이름 OUT.json` | 내장 템플릿 목록·내용·JSON 저장 | 0 |
| `style IN OUT.ass --template 이름\|파일.json` | 템플릿 모양의 ASS 파일 생성 | 0 |
| `burn VIDEO SUBS OUT.mp4 --template ...` | FFmpeg로 영상에 자막 굽기 | 0 |

입력·환경 오류는 종료 코드 2와 한 줄 메시지입니다. 출력 형식은 확장자(.srt/.vtt)로 정하고 `--format`으로 바꿉니다. ASS는 모양이 필요하므로 `convert`가 아니라 `style`로 만듭니다.

### 입력 파일 읽기

인코딩은 편집기의 자막 가져오기와 같은 순서로 정합니다. `--encoding` → BOM → UTF-8 → charset-normalizer 판별. 판별기가 고른 경우 "자동 판별"이라고 표시하니 글자를 확인하세요. 판별에 실패하면 후보별 첫 자막 미리보기를 보여 주므로 글자가 제대로 보이는 `--encoding`을 고릅니다. 글자가 없거나 시각이 잘못된 자막은 빼고 무엇을 뺐는지 표준 오류에 적습니다.

### 표시 규칙 옵션

`info`, `check`, `shape`, `style`, `burn`이 받습니다. 비우면 언어 기본값(한국어 지침, `--language en`이면 영어 지침)입니다.

```text
--language ko|en   --max-chars 16   --max-lines 2   --max-cps 12   --min-duration 1   --max-duration 7
```

글자 수는 폭 단위입니다(한글 1, 라틴·공백 0.5). 근거는 [오픈소스 통합](OPEN_SOURCE_INTEGRATIONS.md)의 자막 표시 규칙 기준에 있습니다.

## 자막 템플릿

템플릿은 **영상에 굽는 자막의 모양**입니다. 어떤 자막을 언제 보일지(줄바꿈·분할·구간)는 표시 규칙이 정하고, SRT·VTT 파일에는 모양이 들어가지 않습니다.

내장 템플릿:

| 이름 | 설명 |
|---|---|
| `default` | 흰 글자에 검은 외곽선. 템플릿 도입 전 렌더와 같은 값이라 기존 편집본의 모양이 바뀌지 않습니다 |
| `shorts-bold` | 굵고 큰 글자(72)에 두꺼운 외곽선 |
| `yellow` | 노란 굵은 글자에 검은 외곽선 |
| `box` | 검은 반투명 상자 위에 흰 글자 |
| `top` | 자막을 화면 위에. 화면 제목은 아래로 |
| `minimal` | 작은 글자(56)에 얇은 외곽선, 그림자 없음 |

값을 바꾸려면 내보내서 고칩니다.

```bash
r4-subtitles templates export yellow mine.json
# mine.json의 name, font_size, primary_color 등을 고친 뒤
r4-subtitles style captions.srt captions.ass --template mine.json --width 1080 --height 1920 --title "화면 제목"
r4-subtitles burn source.mp4 captions.srt result.mp4 --template mine.json
```

템플릿 JSON 항목:

| 항목 | 값 | 기본 |
|---|---|---|
| `name` | 소문자·숫자·하이픈, 40자 이하 | 필수 |
| `label`, `description` | 화면 표시 이름·설명 | 필수 / 빈 값 |
| `font_name` | 글꼴 이름. 쉼표·중괄호·역슬래시 불가(ASS 파일이 깨지거나 명령이 주입됨) | `Noto Sans CJK KR` |
| `font_size` | 20~120 | 64 |
| `bold`, `italic` | 참/거짓 | 거짓 |
| `primary_color`, `outline_color`, `back_color` | `#RRGGBB` 또는 `#RRGGBBAA`(AA는 불투명도, FF가 불투명) | 흰 / 검정 / 검정 |
| `outline`, `shadow` | 0~20 | 3 / 1 |
| `border_style` | `outline`(외곽선+그림자) 또는 `box`(상자, `back_color`가 상자 색, `outline`이 상자 여백) | `outline` |
| `position`, `horizontal` | `bottom`/`middle`/`top`, `left`/`center`/`right` | `bottom` / `center` |
| `margin_horizontal` | 좌우 여백 px | 50 |
| `margin_vertical_ratio` | 화면 높이 대비 위·아래 여백 비율 | 0.13 |
| `letter_spacing` | 자간 | 0 |

글자 크기는 `--font-size`(또는 편집본의 `font_size`)를 주면 템플릿 값보다 우선합니다. 화면 제목은 자막의 반대쪽 끝(자막이 아래면 위)에 같은 모양으로 놓입니다.

## 관리화면·API 연결

- 편집기의 **자막 템플릿** 선택이 `POST /clips`의 `subtitle_template`로 저장되고 렌더가 그 모양으로 굽습니다. 선택 구간을 단계별 제작으로 보내면 `workflow.clip.subtitle_template`로 함께 갑니다.
- `GET /subtitle-templates`가 내장 템플릿을 돌려줍니다. 모르는 이름은 저장 전에 422로 거절합니다.
- 편집본 기록 `clip_edits.subtitle_style`에 `template`와 실제 글자 크기가 남습니다. 템플릿 이전 기록은 `font_size`만 있으며 `default`로 렌더됩니다.
- 파일로 만든 사용자 템플릿(JSON)은 명령줄 전용입니다. 서버에는 내장 템플릿만 있고 업로드·저장 화면은 없습니다.

## 검증 범위

`tests/test_subtitle_templates.py`, `tests/test_subtitle_tool.py`가 값 검증, 색·정렬 변환, 파일 읽기·쓰기, 규칙 적용, 렌더 연결을 확인합니다. `burn`의 실제 FFmpeg 합성과 글꼴 표시는 이 저장소의 CI 환경(FFmpeg 설치)이나 워커 이미지에서 따로 확인해야 하며, 템플릿별 화면 안 배치 실측(`scripts/measure_subtitles.py`)은 `default` 값으로만 되어 있습니다.
