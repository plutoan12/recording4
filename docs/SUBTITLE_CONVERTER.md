# 자막 변환기와 편집 프로그램 연결

기존 서버와 독립적으로 실행하는 로컬 명령입니다. `pipeline.interchange`에 구현하며,
전용 `.venv-converter`에 기존 프로젝트와 같은 `pysubs2==1.8.0`을 설치합니다.
기존 웹 화면/API에 붙인 기능은 아닙니다.

## 설치와 실행

프로젝트 폴더에서 실행합니다. Python 3.11 이상이 필요합니다.

```sh
sh scripts/install_converter.sh
sh scripts/convert_subtitles.sh examples/converter-sample.srt .runtime/sample.ass
sh scripts/convert_subtitles.sh examples/converter-sample.srt .runtime/editor-bundle --target all --template examples/caption-template.json
```

이미 존재하는 출력 파일/폴더는 덮어쓰지 않습니다. 새 출력 이름을 사용하세요.
옛 한국어 자막은 `--encoding cp949`를 지정합니다. UTF-8과 UTF-16/32 BOM은 자동 처리하며,
깨진 글자를 조용히 저장하지 않도록 다른 인코딩은 추측하지 않습니다.

| 형식 | 입력 | 출력 | 범위 |
|---|---|---|---|
| SRT / VTT | 가능 | 가능 | 시간·텍스트·줄바꿈. 출력 스타일 제거 |
| ASS / SSA | 가능 | 가능 | pysubs2 스타일·이벤트. ASS 전용 기능은 SSA에서 손실 가능 |
| SMI / SAMI | 가능 | 불가 | 단일 언어, CSS 제외. 마지막 종료 SYNC 필수 |
| TTML | 가능 | 가능 | pysubs2가 지원하는 TTML 부분집합 |
| JSON | 가능 | 가능 | pysubs2 JSON 스키마. 편집 프로그램의 임의 JSON은 아님 |

SMI는 다음 SYNC 시각으로 현재 자막을 끝냅니다. 마지막에 빈 SYNC가 없으면
종료 시간을 임의로 만들지 않고 오류를 반환합니다. 복수 언어 클래스 선택은 미지원입니다.
시간 역전·음수·비어 있는 입력을 거부하고, 겹치는 자막은 유지하면서 보고합니다.
입력 파일은 변경하지 않습니다. 출력은 UTF-8입니다.

## 네 편집 프로그램

`--target premiere|after-effects|capcut|davinci|all`로 출력 묶음을 만듭니다.

| 프로그램 | 생성 파일 | 가져오는 방법 |
|---|---|---|
| Premiere | `premiere/captions.srt` | 파일 가져오기 후 시퀀스에 배치 |
| After Effects | `after-effects/captions.jsx` | File → Scripts → Run Script File |
| CapCut Desktop/Web | `capcut/captions.srt` | 자막 가져오기 |
| DaVinci Resolve | `davinci/captions.srt` | SRT 가져오기 후 자막 트랙에 배치 |

After Effects 스크립트는 별도의 30fps 컴포지션에 자막별 텍스트 레이어를 생성합니다.
시간은 초 단위로 전달합니다. 렌더 결과는 컴포지션 프레임 격자에 따릅니다.
기존 프로젝트를 저장하거나 기존 레이어를 변경하지 않습니다. 글꼴이 없으면 앱의 대체
글꼴 결과를 확인해야 합니다. 다른 세 프로그램에는 SRT로 글자와 시간만 전달합니다.
서체·색·배치는 각 편집기에서 적용하세요.

묶음에는 `archive.ass`, `archive.json`, `template.json`, `report.json`, `README.txt`도 있습니다.
archive는 파싱/선택적 템플릿 적용 이후의 데이터이며 원본 파일의 바이트 단위 백업은 아닙니다.
원본은 따로 보관하세요. `report.json`은 스타일 손실·겹침·미지원 범위를 기록합니다.

## 공통 스타일 템플릿 규칙

`examples/caption-template.json`은 recording4 전용 설정입니다.
`version=1`, `font`, `size`, `color=#RRGGBB`, ASS 방식의 `alignment=1..9`,
`margin_v`, `width`, `height`를 받습니다. 크기는 기준 화면의 픽셀 단위입니다.
정렬은 숫자 키패드처럼 1/2/3이 아래, 4/5/6이 가운데, 7/8/9가 위입니다.

- `--template` 생략: ASS/JSON 원본 스타일을 중간 데이터에 유지합니다.
- `--template` 지정: 기존 스타일과 인라인 효과를 공통 템플릿으로 대체합니다.
- ASS 출력: 지정한 폰트·색·크기·정렬·세로 여백과 화면 크기를 기록합니다.
- AE 출력: 공통 템플릿을 사용합니다. 생략하면 기본 템플릿입니다. 가로 가장자리 여백은 40px.
- SRT/VTT 출력: 템플릿 모양을 담을 수 없는 이 경로에서는 스타일을 제거하고 손실을 알립니다.
- 모션·키프레임·외부 플러그인 효과를 다른 앱의 효과로 추측해서 치환하지 않습니다.

**MOGRT/AEP, CapCut 네이티브 프로젝트·템플릿, Resolve DRP/Fusion 템플릿의 상호 변환은
아직 구현하지 않았습니다.** 이 기능에는 실제 입력 템플릿, 앱 버전과 목표 출력 예시를 기준으로
앱별 추가 어댑터 및 해당 앱에서의 검증이 필요합니다. 네 앱용 자막 출력과는 구분합니다.

## 검증

```sh
.venv-converter/bin/python -m pip install pytest==8.3.4 ruff==0.8.4
.venv-converter/bin/pytest --noconftest tests/test_interchange.py -q
.venv-converter/bin/ruff check packages/pipeline/pipeline/interchange.py tests/test_interchange.py
```

`--noconftest`는 DB/API용 전역 fixture를 제외합니다. 이 모듈은 DB와 무관한 순수 변환 코드입니다.
자막 왕복 변환, 스타일 유지/제거, BOM/CP949, 잘못된 시간/템플릿, 겹침 보고, 네 앱 출력,
JSX 문자열 이스케이프, 원본 덮어쓰기 방지를 검사합니다.
각 편집 앱에서의 실제 가져오기·화면 모양·영상 렌더 결과는 아직 검증하지 않았습니다.

## 확인한 공식 자료

- [pysubs2 지원 형식](https://pysubs2.readthedocs.io/en/latest/supported-formats.html)
- [Premiere 자막 형식](https://helpx.adobe.com/premiere/desktop/add-text-images/insert-captions/supported-file-formats-for-captions.html)
- [After Effects 스크립트 실행](https://helpx.adobe.com/after-effects/desktop/automate-in-after-effects/automate-animation/scripts.html)
- [CapCut 자막 가져오기](https://www.capcut.com/help/how-to-import-subtitles)
- [Resolve 19 SRT 가져오기](https://documents.blackmagicdesign.com/ae/SupportNotes/DaVinci_Resolve_19_New_Features_Guide.pdf)


이미지와 자막으로 장면을 자동 만들려면 [이미지 템플릿 자동 제작](TEMPLATE_FACTORY.md)을 참고하세요.
