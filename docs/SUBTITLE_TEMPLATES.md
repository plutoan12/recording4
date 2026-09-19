# 자막 템플릿

편집기와 단계별 제작 화면에서 스타일을 고르고 **스타일 미리보기**로 한국어 예시를 확인합니다. 선택은 렌더 작업에 저장됩니다. 미리보기는 6초짜리 예시 문장이며 실제 영상·편집 대본 미리보기는 아닙니다. 실제 결과물은 제작 후 검수합니다.

| 선택 | ID | 표시 |
|---|---|---|
| 기본 번역형 | classic | 흰 글씨·검은 외곽선, 기존 작업 기본값 |
| 검은 배경형 | box | 반투명 검은 배경 |
| 숏폼 강조형 | shorts | 노란 굵은 글씨·문장 등장 확대/페이드 |
| 화자별 색상형 | speaker | 첫 등장 순서로 4색 순환, 미지정은 흰색 |
| 원문·번역 병기형 | bilingual | 번역 위에 작은 원문 |

한국어 번역 자막만 만들려면 **자막만 번역·원래 음성 유지**, 대상 언어 `ko`를 선택합니다. 템플릿·미리보기 자체는 유료 API를 호출하지 않습니다. 번역은 기존 비용 한도와 설정을 따릅니다.

화자 ID는 편집기에서 입력하거나 기존 화자 분리 결과를 사용합니다. 대본 저장·구간 자르기·문장 분할·번역·더빙 시각 정합을 거쳐 보존합니다. 색상은 한 결과물 안에서 일관되며 다른 작업의 전역 인물 식별을 뜻하지 않습니다.

번역 단계가 `original_text`를 함께 저장하므로 병기형은 새 번역 작업에 바로 적용됩니다. 예전 작업이나 원어 작업처럼 원문 메타데이터가 없는 경우 한 언어만 표시합니다. 숏폼 효과는 문장 단위이며 단어별 강조·노래방 싱크는 포함하지 않습니다.

## 구현과 재현

- `pipeline/subtitle_templates.py`의 `build_ass`를 API 예시와 FFmpeg 워커가 공유합니다. 기존 줄 나눔·읽기 속도 규칙도 공유합니다.
- 인증된 `GET /subtitle-templates`, `POST /subtitle-templates/preview`가 목록과 예시 ASS를 반환합니다.
- JASSUB 2.5.16은 미리보기를 열 때 로드하며 로컬 배포 글꼴을 사용합니다. 외부 글꼴 검색은 끕니다. 브라우저는 Worker·OffscreenCanvas·WebAssembly 지원이 필요합니다.
- Noto Sans CJK KR 글꼴 파일은 약 16MB입니다. 브라우저와 서버가 같은 글꼴 계열을 사용하지만 버전·해상도에 따라 픽셀 결과는 달라질 수 있습니다.
- `python scripts/verify_subtitle_templates.py --output /tmp/template-check`로 FFmpeg·ffprobe가 있는 환경에서 5개 MP4/PNG와 원음 유사도 보고서를 생성합니다. 유료 서비스나 실제 사용자 영상은 쓰지 않습니다.

## 오픈소스 출처

- [pysubs2](https://github.com/tkarabela/pysubs2): 기존 1.8.0 의존성, MIT, ASS 생성.
- [JASSUB](https://github.com/ThaUnknown/jassub): npm 2.5.16 그대로 사용. JS 래퍼는 MIT이고 WASM 및 포함 라이브러리는 복합 라이선스입니다. MIT 단일 라이선스로 취급하지 않습니다. [배포 고지](../apps/web/public/licenses/README.txt)를 함께 제공합니다.
- [Noto CJK](https://github.com/notofonts/noto-cjk): `Sans/OTF/Korean/NotoSansCJKkr-Regular.otf`, SIL OFL 1.1. 원본 글꼴과 OFL을 함께 배포합니다.

tscaps·pycaps·Remotion 기반의 별도 렌더 엔진은 이번 변경에 설치하지 않았습니다. 5개 ASS 스타일은 이 저장소에서 작성했습니다.
