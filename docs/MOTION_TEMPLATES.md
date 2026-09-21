# 외부 자료 기반 모션 자막 5종

Mixkit의 공개 이름표/타이틀 유형, Material Design의 모션 원칙, Aegisub의
ASS 공식 문법을 참고해 코드를 직접 작성했습니다. Mixkit 템플릿 파일이나 미디어를
다운로드해 변환·재배포한 것은 아닙니다. 실제 외부 포함 소재는 Google Fonts 공식
저장소의 Noto Sans KR이며 원본과 SIL OFL 1.1 라이선스를 함께 제공합니다.

## 실행

```sh
sh scripts/make_motion_templates.sh examples/converter-sample.srt .runtime/my-motion
```

`--preset interview|news|cinema|pop|chapter|all`, `--no-render`, `--encoding cp949`,
`--fonts 폴더경로`를 지원합니다. 이 Mac에는 `.runtime/external-fonts`에
NotoSansKR.ttf 및 OFL.txt를 내려받았습니다. 시스템 전체 글꼴 설치는 하지 않았습니다.
다른 컴퓨터에서는 아래 Google Fonts 출처에서 두 파일을 받아 --fonts 폴더에 둡니다.
FFmpeg는 기존 scripts/install_converter.sh로 설치합니다.

| 유형 | 디자인 | 등장 효과 |
|---|---|---|
| interview | 짙은 청록 배경과 민트 이름표 | 옆에서 슬라이드 + 페이드 |
| news | 남색 격자와 빨간 배너 | 슬라이드 + 페이드 |
| cinema | 어두운 화면과 금색 포인트 | 페이드 |
| pop | 보라색과 라임색 큰 글자 | 88%에서 100%로 확대 + 페이드 |
| chapter | 크림색 바탕과 오렌지 구분선 | 슬라이드 + 페이드 |

대사와 타이밍은 입력 자막에서 읽습니다. 긴 대사는 두 줄까지 자동 줄나눔하며,
영역을 넘거나 자막 시간이 겹치면 오류로 알립니다. 소스의 PRESETS를 수정해 색·크기·위치·
라벨을 바꿀 수 있습니다. 출력 presets.json은 사용한 값의 기록이며 자동으로 다시 읽는
설정 입력 파일은 아닙니다. CHAPTER / 01 등 장식 라벨은 기본 샘플 값입니다.

## 결과물

- preview.mp4: 1080p 30fps H.264 무음 영상. 프리미어/AE/캡컷/다빈치에서 영상으로 사용.
- editable.ass: 글자·도형·시각·모션이 편집 가능한 ASS. Aegisub 등 지원 도구에서 수정.
- captions.srt: 스타일/모션 없는 원래 자막 데이터.
- fonts/: 실제 사용한 글꼴 원본과 OFL 저작권/라이선스.
- sources.json: 각 외부 자료의 출처와 참고/사용 범위.
- report.json: 폰트 SHA-256, 출력과 한계 기록.

ASS는 영상 위에 올릴 수 있으며 기본 전체 배경색은 MP4 렌더에서 적용합니다.
ASS가 모든 편집기에서 스타일 그대로 열리는 것은 아닙니다. MOGRT·CapCut·Fusion 고유
템플릿 파일은 포함하지 않습니다. 제작 결과를 승인하거나 자동 게시하지 않습니다.
기존 결과는 덮어쓰지 않으며 전체 생성 성공 후에만 최종 폴더를 만듭니다.

## 참고 자료와 사용 범위

- https://mixkit.co/free-after-effects-templates/lower-thirds/ — 유형 참고만.
- https://mixkit.co/free-premiere-pro-templates/titles/ — 유형 참고만.
- https://m1.material.io/motion/duration-easing.html — 모션 원칙 참고.
- https://aegisub.org/docs/latest/ass_tags/ — move/fad/t/drawing 문법 구현.
- https://github.com/google/fonts/tree/main/ofl/notosanskr — 원본 글꼴 사용.
- https://raw.githubusercontent.com/google/fonts/main/ofl/notosanskr/OFL.txt — 라이선스 원문.

2026-09-20 검증: 변환·이미지 템플릿·모션 템플릿 총 50개 테스트 통과,
새 코드 ruff 통과. 모션 영상 5개 실제 렌더 및 전체 디코딩, 샘플 프레임 확인.
편집 앱에서의 실제 가져오기 및 네이티브 프로젝트 검증은 하지 않았습니다.

## 두 번째 시리즈: 기존 생성기로 새 디자인 제작

`paper`, `neon`, `quote`, `terminal`, `split`, `card` 6종을 추가했습니다. 노트 종이, 네온 프레임, 인용문, 터미널 로그, 분할 타이틀, 메시지 카드 디자인입니다. 기존 5종과 합쳐 총 11종을 선택할 수 있습니다. 기존 OFL 글꼴과 ASS 렌더러를 재사용하며, 외부 유료 템플릿 파일은 사용하지 않았습니다.

```sh
./scripts/make_motion_templates.sh examples/motion-series-02.srt \
  .runtime/paper-custom --preset paper
```

새 모션은 아래에서 올라오기(rise), 왼쪽부터 나타나기(wipe)입니다. 다른 디자인에는 기존 slide/fade/pop을 적용합니다. 결과는 MP4 미리보기·편집 가능한 ASS·스타일 없는 SRT이며, 편집기 네이티브 프로젝트가 아닙니다.

## 세 번째 시리즈: 키네틱 타이포그래피

`typewriter`(글자별 등장), `punch`(첫 단어 크기 강조와 확대 등장), `cascade`(줄별 등장), `stamp`(회전·축소 도장 효과)를 추가해 총 15종입니다. `examples/motion-series-03.srt`로 만든 결과는 `.runtime/motion-pack-03`에 있습니다. 전체 글자 폭을 유지한 채 투명도로 등장시켜 타이핑 중 정렬이 흔들리지 않게 합니다. 등장 시간은 자막 길이의 1/3 이내입니다. 한글 완성형 음절 기준이며, 결합 문자/이모지 묶음을 하나의 글자로 처리하는 고급 분할은 지원하지 않습니다. 앞서 받은 외부 AEP를 변환한 것이 아니라 기존 자체 엔진을 확장한 디자인입니다.

## 세로형·단어 시각 확장

[세로형 단어 강조 생성기](PORTRAIT_CAPTIONS.md)를 추가했습니다. 별도 words.json을 받아
1080×1920의 색상 강조·박스 강조·작은 확대 3종을 출력합니다. 기존 15종의 포인트 색을
선택할 수 있으며, 기존 가로형 장식과 모션은 그대로 유지합니다.
