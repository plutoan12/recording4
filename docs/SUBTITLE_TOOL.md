# 자막 파일·템플릿 도구

자막 파일(SRT·WebVTT·ASS)을 검사·변환·다듬고, 자막 템플릿(글꼴·색·외곽선·위치)을 골라 ASS 파일이나 영상에 굽는 명령줄 도구입니다. DB·큐·유료 API 없이 파일만 다룹니다. 서버의 편집기·렌더와 **같은 코드**(`pipeline.subtitle_files`, `pipeline.subtitles`, `pipeline.subtitle_templates`)를 쓰므로 여기서 확인한 결과가 서버 렌더와 같습니다.

## 실행

```bash
pip install -e ".[dev]"          # 설치하면 r4-subtitles 명령이 생깁니다
r4-subtitles --help
python -m pipeline.subtitle_tool --help   # 같은 도구
```

`burn`·`preview`·`sheet`는 FFmpeg(`ffmpeg`, `ffprobe`)와 글꼴이 필요합니다. 워커 Docker 이미지에는 들어 있습니다. 경로는 `R4_FFMPEG_BINARY`, `R4_FFPROBE_BINARY`, 글꼴 디렉터리는 `R4_FONTS_DIR`로 줄 수 있습니다(아래 글꼴 절).

## 명령

| 명령 | 하는 일 | 종료 코드 |
|---|---|---|
| `info FILE` | 인코딩, 자막 수, 구간, 규칙 위반 수 요약 | 0 |
| `check FILE [--json]` | 표시 규칙 위반을 자막 번호별로 보고. 글자는 고치지 않음 | 위반 있으면 1 |
| `convert IN OUT` | SRT·VTT·ASS → SRT 또는 VTT. 글자·시각 그대로, 꾸밈 표기만 벗김 | 0 |
| `shape IN OUT` | 줄바꿈·분할 규칙을 적용해 저장. 서버가 굽는 자막과 같은 결과 | 0 |
| `shift IN OUT --offset 초` | 시각 이동. 0초 앞으로 나간 자막은 자르고 다 나간 자막은 뺌 | 0 |
| `cut IN OUT --start 초 --end 초` | 구간만 남기고 구간 시작을 0초로 | 0 |
| `templates list` / `show 이름` / `export 이름 OUT.json` / `check` | 내장 템플릿 목록(카테고리별)·내용·JSON 저장·글꼴 확인 | check는 문제 있으면 1 |
| `preview OUT.png --template 이름` | 템플릿 하나를 PNG 한 장으로 | 0 |
| `sheet OUT.png [--category ...] [--templates ...]` | 내장 템플릿 전부(또는 일부)를 한 장의 PNG 시트로 | 0 |
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

내장 템플릿은 카테고리별로 69종입니다. 인스타그램 브이로그 편집자들이 파는 "자막 템플릿 팩"의 흔한 모양(파스텔 상자, 네온 글로우, 픽셀, 통통한 외곽선, 손글씨, 영화 자막, 레트로)을 libass가 그릴 수 있는 값으로 옮긴 것입니다. 전체 목록은 `r4-subtitles templates list`, 실제 렌더 모양은 `r4-subtitles sheet`로 봅니다.

| 카테고리 | 이름 | 모양 |
|---|---|---|
| 기본 | `default` | 흰 글자에 검은 외곽선. 템플릿 도입 전 렌더와 같은 값이라 기존 편집본의 모양이 바뀌지 않습니다 |
| 기본 | `shorts-bold`, `yellow`, `top`, `minimal`, `clean-white`, `gmarket-yellow`, `pretendard-clean` | 굵은 강조, 예능 노랑, 상단 배치, 얇은 외곽선, 선플라워·지마켓·프리텐다드 |
| 브이로그 제목 | `vlog-lime`, `vlog-pink`, `fire-red`, `spring-glow`, `title-sticker`, `pink-sticker`, `solid-shadow`, `jalnan-sticker`, `jalnan-yellow`, `ssurround-lime`, `pop-yellow-3d` | Black Han Sans·Gasoek One·잘난체·써라운드 굵은 제목, 스티커 이중 외곽선, 입체 그림자, 봄 느낌 글로우 |
| 귀여운 외곽선 | `bubble-white`, `bubble-sky`, `bubble-pink`, `round-white`, `mint-pastel`, `playful-tilt`, `lilac-sticker`, `cute-lemon`, `tilt-sticker`, `jalnan-pink-sticker`, `ssurround-sky-sticker`, `ssurround-peach`, `simplehae-lilac` | Bagel Fat One·Dongle·Yeon Sung·잘난체·카페24 써라운드·심플해 통통 글자에 스티커 외곽선, 살짝 기울임, ★☆♡ 장식 |
| 네온·글로우 | `neon-pink`, `neon-blue`, `neon-purple`, `lavender-glow`, `cyber-cyan`, `neon-hollow-pink`, `neon-hollow-round`, `neon-hollow-lime` | 밝은 글자 주변에 색이 번지는 네온사인, 속 빈 네온(선만 빛남), 오르빗 사이버 |
| 픽셀 | `pixel-heart`, `pixel-mint`, `pixel-box` | Galmuri 도트 글꼴, 하트 장식, 연노랑 상자 |
| 상자·카드 | `box`, `pink-cabinet`, `note-yellow`, `note-pink`, `note-blue`, `tmi-blue`, `white-card`, `black-tag`, `cyan-strip`, `news-bar`, `wanted-mint-card` | 파스텔 상자·테두리 카드·검은 태그·빨간 뉴스 바·민트 카드. 소제목, 짧은 한마디, 제품 정보에 |
| 손글씨 | `pen-white`, `melody-pink`, `gamja-yellow`, `brush-white`, `brush-shadow`, `diary`, `brush-red` | 나눔손글씨 펜·붓, 하이멜로디, 감자꽃, 서툰이야기, 독도 붓글씨 |
| 레트로·세리프 | `movie-serif`, `luxury-serif`, `retro-orange`, `retro-blue-pixel`, `retro-blue-3d`, `songmyung-cream`, `elegant-serif`, `grandiflora-pink` | 고운바탕 영화 자막, 모이라이 레트로, 송명·디필레이아·그랜디플로라 세리프, 파란 도트 |

값을 바꾸려면 내보내서 고칩니다.

```bash
r4-subtitles templates export neon-pink mine.json
# mine.json의 name, primary_color, glow, prefix 등을 고친 뒤
r4-subtitles style captions.srt captions.ass --template mine.json --width 1080 --height 1920 --title "화면 제목"
r4-subtitles burn source.mp4 captions.srt result.mp4 --template mine.json
```

템플릿 JSON 항목:

| 항목 | 값 | 기본 |
|---|---|---|
| `name` | 소문자·숫자·하이픈, 40자 이하 | 필수 |
| `label`, `description` | 화면 표시 이름·설명 | 필수 / 빈 값 |
| `category` | `basic` `vlog` `cute` `neon` `pixel` `box` `handwriting` `retro` | `basic` |
| `sample` | 미리보기 예문. 비우면 `label` | 빈 값 |
| `font_name` | 글꼴 이름. 아래 글꼴 목록에 있는 이름만 실제로 그려집니다. 쉼표·중괄호·역슬래시 불가 | `Noto Sans CJK KR` |
| `font_size` | 20~120 (1080x1920 기준) | 64 |
| `bold`, `italic` | 참/거짓 | 거짓 |
| `primary_color`, `outline_color` | `#RRGGBB` 또는 `#RRGGBBAA`(AA는 불투명도, FF가 불투명) | 흰 / 검정 |
| `back_color` | 외곽선 방식의 그림자 색 | 검정 |
| `box_color` | 상자 방식의 상자 색 | 검정 |
| `outline`, `shadow` | 0~20. 상자 방식에서는 `outline`이 상자 여백 | 3 / 1 |
| `outline2`, `outline2_color` | 바깥 테두리(스티커 느낌). 외곽선 방식에서만 그리며 이벤트를 두 겹으로 냅니다 | 0 / 흰색 |
| `angle` | 글자 기울기(도, -30~30). 양수가 반시계 방향 | 0 |
| `hollow` | 참이면 채움을 투명으로 두고 외곽선만 그립니다. `glow`와 함께 쓰면 속 빈 네온 | 거짓 |
| `extrude`, `extrude_color` | 입체 돌출 깊이(px, 0~16)와 색. 그림자를 1px씩 밀어 쌓아 두께처럼 보입니다 | 0 / #222222 |
| `accent_color` | 자막 글자 안의 `[[...]]` 부분을 그리는 색. 비우면 표기만 빼고 같은 색 | 빈 값 |
| `glow` | 0~20. 글자 주변 번짐(ASS `\blur`). 외곽선 색이 번져 네온처럼 보입니다 | 0 |
| `border_style` | `outline`(외곽선+그림자), `box`(상자), `box-outline`(상자+테두리) | `outline` |
| `box_radius` | 상자 모서리 반지름(px). 0이면 libass의 각진 상자, 0보다 크면 글자 폭을 재서 글자 뒤에 둥근 사각형을 그립니다. 여백은 `outline`, 테두리 두께는 `outline2` | 0 |
| `position`, `horizontal` | `bottom`/`middle`/`top`, `left`/`center`/`right` | `bottom` / `center` |
| `margin_horizontal` | 좌우 여백 px | 50 |
| `margin_vertical_ratio` | 화면 높이 대비 위·아래 여백 비율 | 0.13 |
| `letter_spacing` | 자간 | 0 |
| `prefix`, `suffix` | 자막 앞뒤 장식 기호(★ ☆ ♡ ✳ ♪ ✧ 등), 8자 이하. 글꼴에 있는 글자여야 그려지고 이모지는 안 됩니다 | 빈 값 |

### 이모지

libass는 컬러 이모지(🍓🍵💗)를 못 그립니다. 자막 글자에 이모지가 있으면 그 구간에만 흑백 Noto Emoji 글꼴을 붙여 선 그림으로 그립니다(`pipeline/subtitle_markup.py`의 `split_emoji`). 색은 자막 글자 색을 따릅니다. ★☆♡♪✳✧ 같은 기호는 한글 글꼴에 있으므로 그대로 둡니다. 글꼴 대체에 맡기면 픽셀 글꼴의 이모지가 걸리는 등 결과가 달라져 명시합니다.

### 단어별 강조 `[[...]]`

자막 내용에서 `[[딸기]]말차라떼`처럼 감싼 부분은 템플릿의 `accent_color`로 그립니다(속 빈 글자는 선 색이 바뀝니다). 표기는 굽는 자막 전용이라 SRT·VTT 파일, 화면 제목, 편집기 표시에서는 괄호 없이 글자만 나갑니다. 표시 규칙이 긴 자막을 나눠 표기가 두 자막에 걸치면 앞 자막은 끝까지 강조하고 뒤 자막의 짝 없는 `]]`는 뺍니다. 규칙은 `packages/pipeline/pipeline/subtitle_markup.py`에 있습니다. 강조 색이 없는 템플릿에서는 표기만 빠집니다.

글자 크기는 `--font-size`(또는 편집본의 `font_size`)를 주면 템플릿 값보다 우선합니다. 화면 제목은 자막의 반대쪽 끝(자막이 아래면 위)에 같은 모양으로 놓이되 장식은 붙지 않습니다.

둥근 상자(`box_radius` > 0)는 ASS로는 못 그리므로 설치된 글꼴 파일을 fontTools로 열어 글자 폭을 재고(`packages/pipeline/pipeline/subtitle_metrics.py`) 그 둘레에 벡터 둥근 사각형을 그립니다. 글꼴 파일은 `R4_FONTS_DIR`이나 fontconfig에서 찾으며, 못 찾으면 글꼴별 폭 계수로 어림해 상자가 글자와 조금 어긋날 수 있습니다. 워커 이미지에는 글꼴과 fontTools가 모두 있습니다.

상자 색은 libass 동작에 맞춰 넣습니다. libass는 BorderStyle 3(상자)을 **외곽선 색**으로 채우고 BorderStyle 4(상자+테두리)는 뒷색으로 채웁니다. `box_color`를 두고 방식에 따라 알맞은 자리에 넣으므로 JSON에서는 신경 쓰지 않아도 됩니다.

## 글꼴

템플릿이 쓰는 글꼴 35종은 모두 무료로 상업 사용과 영상 삽입이 허용됩니다. 대부분 SIL Open Font License 1.1이고, 잘난체·카페24·지마켓 산스는 각 회사의 자체 라이선스(무료, 수정·판매 금지)입니다. 목록·출처(커밋 해시 고정)·SHA-256·라이선스 링크는 `packages/pipeline/pipeline/subtitle_fonts.py`에 있고, 파일은 저장소에 넣지 않습니다.

| 글꼴(ASS 이름) | 라이선스 | 출처 | 쓰는 템플릿 |
|---|---|---|---|
| Noto Sans CJK KR | OFL | 워커 이미지 `fonts-noto-cjk` 패키지 | 기본 |
| Jua, Black Han Sans, Bagel Fat One, Gaegu, Do Hyeon, Gowun Batang, Nanum Pen, Gugi, Moirai One, Dongle, Single Day, Hi Melody, Gamja Flower, East Sea Dokdo, Gasoek One, Kirang Haerang, Yeon Sung, Sunflower, Cute Font, Nanum Brush Script, Song Myung, Orbit, Diphylleia, Dokdo, Gothic A1, Poor Story, Grandiflora One | OFL | Google Fonts 저장소(`google/fonts` 커밋 고정) | 브이로그·귀여운·네온·상자·손글씨·레트로 |
| Galmuri11 Regular, Galmuri9 Regular | OFL | `quiple/galmuri` 커밋 고정 | 픽셀 |
| Noto Emoji(흑백) | OFL | Google Fonts 저장소 | 템플릿 글꼴이 아니라 이모지 구간에 자동으로 붙는 대체 글꼴 |
| Jalnan(여기어때 잘난체) | 잘난체 라이선스 | 눈누 `projectnoonnu/noonfonts_four` 커밋 고정 WOFF → OTF 변환 | 잘난체 스티커·노랑·핑크, 네온 퍼플 |
| Cafe24 Ssurround, Cafe24 Simplehae | 카페24 서체 라이선스 | 눈누 `noonfonts_2105_2`·`noonfonts_twelve` WOFF → TTF 변환 | 써라운드 라임·하늘·피치, 심플해, 민트 파스텔, 핑크 캐비닛, 하늘 띠 |
| Gmarket Sans(Bold) | 지마켓 산스 라이선스 | 눈누 `noonfonts_2001` WOFF → OTF 변환 | 지마켓 노랑, 흰 카드 |
| Pretendard(Black), Wanted Sans(Black) | OFL | `orioncactus/pretendard`, `wanteddev/wanted-sans` 커밋 고정 | 프리텐다드 깔끔, 원티드 민트 카드 |

Nanum Pen Script와 Galmuri는 파일 안의 family 이름이 Google Fonts 이름과 달라(`Nanum Pen`, `Galmuri11 Regular`) 템플릿은 파일 이름을 씁니다. 잘난체·지마켓 산스 OTF는 name 테이블이 비어 있어 변환할 때 `Jalnan`, `Gmarket Sans`라는 이름을 써 넣습니다(libass는 이름 없는 글꼴을 등록하지 못합니다). libass는 이름이 다르면 오류 없이 다른 글꼴로 바꿔 그리므로, 내려받기 스크립트가 `fc-scan`으로 이름을 확인하고 `r4-subtitles templates check`가 설치된 컴퓨터에서 다시 확인합니다.

- 워커 이미지: `infra/Dockerfile.worker`가 `scripts/fetch_fonts.py`로 `/usr/share/fonts/truetype/r4`에 설치합니다. WOFF 출처는 fontTools(`[fonts]` 추가 의존성)로 TTF/OTF로 바꿉니다. 이미지를 다시 빌드해야 합니다.
- 로컬: `pip install -e ".[fonts]"` 후 `python scripts/fetch_fonts.py --out .fonts`, 그리고 `--fonts-dir .fonts` 또는 `R4_FONTS_DIR=.fonts`. 워커를 로컬에서 직접 돌릴 때도 `R4_FONTS_DIR`을 읽어 FFmpeg에 넘깁니다.
- 관리화면 미리보기는 Google Fonts에 있는 글꼴만 같은 이름으로 불러오고, 잘난체·카페24·지마켓·Pretendard·Wanted Sans는 비슷한 굵기의 Google 글꼴로 대신 보여 줍니다.

## 미리보기

```bash
r4-subtitles templates check --fonts-dir .fonts                      # 글꼴이 실제로 찾아지는지
r4-subtitles sheet templates.png --fonts-dir .fonts                  # 69종 전부 한 장 (흐름 배치, 1080x약 5000)
r4-subtitles sheet neon.png --category neon pixel --columns 1 --width 720 --text "같은 예문"
r4-subtitles preview one.png --template neon-pink --text "제발... 제발!!!!!" --height 400
```

`sheet`는 기본(`--layout flow`)으로 글자 폭을 재서 한 줄에 들어가는 만큼 채워 넣어 참고 이미지처럼 빽빽하게 만들고, `--layout grid`는 같은 크기 칸에 하나씩 놓습니다. 인스타그램 소개 이미지처럼 템플릿마다 예문 한 줄을 놓고 카테고리 구분 줄과 흐린 별 배경을 넣어 한 프레임으로 렌더합니다. 글자 크기는 칸에 맞춰 줄이므로(글꼴별 폭 계수로 어림) 실제 영상보다 작게 보일 수 있습니다. `--columns 1`로 크게 볼 수 있습니다. CI의 `워커 이미지 빌드`가 실제 글꼴로 시트를 만들어 `subtitle-template-sheet` artifact로 올리고, `templates check`로 글꼴 누락을 잡습니다.

관리화면의 템플릿 선택은 같은 글꼴을 Google Fonts CSS로 불러 **CSS로 흉내 낸** 미리보기를 보여 줍니다. 픽셀 글꼴은 Google Fonts에 없어 고정폭으로 대신하고, 글로우·상자·바깥 테두리·기울임은 `text-shadow`·배경·`transform`으로 근사합니다. 정확한 모양은 시트나 실제 렌더로 확인합니다.

## 관리화면·API 연결

- 편집기의 **자막 템플릿** 선택이 `POST /clips`의 `subtitle_template`로 저장되고 렌더가 그 모양으로 굽습니다. 선택 구간을 단계별 제작으로 보내면 `workflow.clip.subtitle_template`로 함께 갑니다.
- `GET /subtitle-templates`가 내장 템플릿을 돌려줍니다. 모르는 이름은 저장 전에 422로 거절합니다.
- `GET /subtitle-templates`는 카테고리 순서로 돌려주고 `category_label`을 붙입니다. 편집기는 카테고리별 선택과 CSS 미리보기 갤러리를 보여 줍니다.
- 편집본 기록 `clip_edits.subtitle_style`에 `template`와 실제 글자 크기가 남습니다. 템플릿 이전 기록은 `font_size`만 있으며 `default`로 렌더됩니다.
- 파일로 만든 사용자 템플릿(JSON)은 명령줄 전용입니다. 서버에는 내장 템플릿만 있고 업로드·저장 화면은 없습니다.

## 검증 범위

`tests/test_subtitle_templates.py`, `tests/test_subtitle_tool.py`, `tests/test_fetch_fonts.py`가 값 검증, 색·정렬·상자 색 변환, 장식·글로우, 시트 배치, 파일 읽기·쓰기, 규칙 적용, 렌더 연결, 글꼴 체크섬·이름 검사를 확인합니다. FFmpeg가 있으면 시트·미리보기 PNG를 실제로 렌더합니다. 템플릿별 화면 안 배치 실측(`scripts/measure_subtitles.py`)은 `default` 값으로만 되어 있으며, 큰 글꼴(`vlog-lime` 96, `round-white` 110)은 한 줄 글자 수가 기본 규칙(16자)보다 적게 들어갈 수 있습니다.
