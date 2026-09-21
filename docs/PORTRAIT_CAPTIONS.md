# 세로형 단어 강조 자막

1080×1920 세로 화면에 단어(한국어 어절)별 시각을 받아 자막을 제작합니다.
`clean-focus`는 현재 단어 색상, `marker-follow`는 현재 단어 뒤 직사각형 강조 박스,
`soft-pop`은 현재 단어의 색상과 작은 확대 효과입니다. 강조가 끝나면 기본 색으로 돌아갑니다.
단어 위치는 고정되어 강조 중 줄바꿈이나 전체 문장 위치가 흔들리지 않습니다.

```sh
sh scripts/install_converter.sh
sh scripts/make_portrait_captions.sh examples/portrait-words.json \
  .runtime/my-portrait --style clean-focus --theme pop
```

`--no-render`로 자막만 만들 수 있습니다. `--fonts`는 NotoSansKR.ttf와 OFL.txt가 있는 폴더입니다.
기본값은 `.runtime/external-fonts`입니다. 기존 15종의 `--theme` 이름을 사용할 수 있지만
색상 포인트만 재사용하며 가로형 장식과 애니메이션을 세로형으로 복제하는 것은 아닙니다.
폰트 폭 계산을 위해 Pillow 11.3.0을 설치 스크립트에 추가했습니다.

## 입력

```json
{
  "version": 1,
  "timing_source": "manual",
  "cues": [{
    "start_ms": 500,
    "end_ms": 2000,
    "text": "지금 시작하세요",
    "words": [
      {"text": "지금", "start_ms": 500, "end_ms": 900},
      {"text": "시작하세요", "start_ms": 1000, "end_ms": 1800}
    ]
  }]
}
```

모든 시각은 영상 시작 기준 절대 밀리초이며 ASS 저장 정밀도에 맞춰 10ms 배수여야 합니다.
문장·단어는 시간순으로 겹치지 않아야 하며 단어는 해당 문장 시간 안에 있어야 합니다.
각 words.text는 공백 없는 어절입니다. 문장 text를 제공하면 words를 공백으로 연결한 결과와
일치해야 합니다. 다르면 대사 수정 후 타이밍 재확인이 필요하다는 오류를 냅니다.

`timing_source`는 manual(수동), aligned(음성 정렬 결과), estimated(추정) 중 하나이며
작성자가 제공하는 출처 표시입니다. 프로그램이 원음 정확도를 인증하는 값은 아닙니다.
샘플은 무음 디자인 시연용 수동 시각입니다. STT·강제 정렬·SRT 자동 균등 분할은 하지 않습니다.

## 한글 배치

실제 Noto Sans KR 글꼴 폭으로 어절을 보존하며 두 줄까지 줄바꿈합니다. 64px부터 44px까지
줄여도 넘치면 문장을 나누라는 오류를 냅니다. 한국어 형태소를 분석해 조사를 옮기지 않습니다.
자막 중심은 화면 하단 중앙 부근의 고정 영역입니다. 모든 플랫폼 UI를 피한다는 보장은 아니며
실제 휴대전화와 플랫폼에서 위치를 검수해야 합니다. 이모지 전용 폰트 대체는 미구현입니다.

## 출력과 제한

- editable.ass: 단어별 강조와 배치를 보존한 자막. 실제 영상 위 합성 가능.
- captions.srt / captions.vtt: 일반 문장 자막. 단어별 시각·모션은 보존하지 않음.
- words.json: 원래 단어 시각을 보존. 텍스트 변경 후 입력 검증에 재사용.
- preview.mp4: 어두운 배경의 무음 시연 영상. 원본 영상 합성은 별도 작업.
- report.json / fonts: 설정·제한·글꼴·라이선스.

기존 결과를 덮어쓰지 않으며 렌더 실패 시 최종 폴더를 남기지 않습니다.
ASS 명령 해석을 방지하기 위해 화면의 역슬래시·중괄호는 전각으로 표시합니다.
MOGRT/AEP/CapCut/Fusion 고유 프로젝트 출력과 실제 앱 가져오기는 미검증입니다.
인물 뒤 타이틀은 후속 작업입니다.

2026-09-20: 관련 독립 테스트 73개 통과, Ruff 통과. 세로형 3개 영상 전체 디코딩과
비교 이미지 육안 검수 완료. 전체 서버 테스트는 실행하지 않았습니다.

## 이중 자막·화자 이름표 확장

각 cue에 `translation`과 `speaker` 문자열을 선택적으로 넣을 수 있습니다.
예시는 `examples/portrait-bilingual.json`입니다. 번역은 원문 아래 최대 두 줄,
화자는 위쪽 이름표로 표시합니다. 화자는 등장 순서대로 네 가지 색을 배정받으며
다시 등장할 때 같은 색을 사용합니다. 다섯 번째부터 색은 반복됩니다.
이름표는 한 줄이며, 이름이 길거나 번역이 영역을 넘으면 제작 전에 오류를 냅니다.

```sh
sh scripts/make_portrait_captions.sh examples/portrait-bilingual.json \
  .runtime/my-bilingual --style soft-pop --theme neon
```

번역이 있으면 `translated.srt/vtt`, `bilingual.srt/vtt`도 출력합니다.
번역 없는 구간은 translated 파일에 넣지 않고, bilingual에는 원문만 유지합니다.
`report.json`의 translated_cues/untranslated_cues로 누락 수를 확인할 수 있습니다.
이름표는 ASS/영상에 표시하며 일반 자막 파일에는 삽입하지 않습니다.
입력 번역과 화자명을 그대로 사용하므로 자동 번역·화자 인식·음성 정렬 기능은 아닙니다.

두 번째 샘플 팩 `.runtime/portrait-pack-02`에는 이중 자막, 화자 이름표,
두 기능을 조합한 자막의 영상 3개와 33초 합본이 있습니다. 자체 대본과 영어 번역,
수동 시연 타이밍을 사용했습니다. 2026-09-20 관련 독립 테스트 81개와 Ruff 통과,
각 영상·합본 전체 디코딩 및 비교 이미지 검수 완료. 네이티브 편집 앱 검증은 미실시입니다.

## 실제 음성 연결

[음성 자막 실행 안내](AUDIO_CAPTIONS.md)의 `make_audio_captions.sh`로 음성/영상을 넣으면
자동 전사 또는 대본 정렬 → words.json → 원음 포함 강조 영상까지 한 번에 생성합니다.
이 문서의 JSON 샘플 명령은 계속 무음이며, 음성 명령을 사용할 때만 소리가 포함됩니다.
