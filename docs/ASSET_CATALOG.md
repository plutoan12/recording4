# 개인용 외부 자료 라이브러리

공개 GitHub 저장소의 공식 API로 파일 목록을 조회하고, 지정한 파일만 내려받는 일회성 수집기입니다. HTML 무차별 크롤링이나 유료 마켓 다운로드 자동화는 포함하지 않습니다. macOS의 curl과 기존 `.venv-converter`를 사용하며 추가 Python 패키지는 없습니다.

```sh
./scripts/collect_assets.sh \
  --sources examples/asset-sources.json \
  --out .runtime/asset-library-02 \
  --max-files 300 --max-mb 100
```

매 실행에 새 출력 폴더를 지정합니다. 기존 catalog.json을 덮어쓰지 않습니다. 원본 요청 실패는 기록하며 성공 자료의 목록은 보존합니다. 오류가 있으면 종료 코드는 1입니다. 자동 재시도·예약 실행은 없습니다. GitHub 요청 제한에 걸리면 오류 내용을 확인한 뒤 다음 수집을 진행합니다.

## 결과

- `index.html`: 네트워크 요청 없이 열리는 이름·앱·저장소 검색, 종류 필터, 개별 파일 다운로드. 폴더 구조를 유지해야 합니다.
- `catalog.json`: 원본 경로, 저장소, 커밋, Git SHA, SHA-256, 라이선스 증거, 수집 상태와 오류.
- `blobs/`: SHA-256별 파일 및 라이선스 원문. 같은 내용은 같은 파일을 사용합니다. 화면의 다운로드 버튼은 원래 파일명으로 저장합니다.
- 분류: preset(FFX·MOGRT·Fusion), subtitle(ASS·SSA·SRT·VTT), script(JSX·Lua·MoonScript).

라이브러리는 수집함입니다. 앱에 자동 설치하거나 코드를 실행하지 않습니다. 스크립트의 의존 파일과 앱 버전은 원본 README에서 확인해야 합니다. 스크린샷·영상 미리보기, 프리셋 적용 결과, 브라우저 검색 조작은 검증하지 않았습니다.

## 수집 정책

`examples/asset-sources.json`에 repo, app, download를 지정합니다. 한 실행은 최대 10개 저장소이고 파일 기본 한도는 300개/100MB, 개별 파일은 5MB입니다. 라이선스 증거 파일은 별도이며 개별 500KB 제한입니다. 심볼릭 링크는 제외합니다. 저장소 트리가 잘리면 해당 저장소를 실패 처리합니다.

MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, Unlicense, CC0-1.0으로 감지되고 라이선스 파일이 있으며 download=true인 소스만 자료 파일 다운로드 후보가 됩니다. 라이선스 파일과 커밋을 같이 남기지만, 저장소 라이선스만으로 개별 자산의 재배포 권리를 확정하지 않습니다. 모든 항목은 `distribution=review_required`, `validation=not_tested`로 기록합니다. 라이선스가 불명확하면 메타데이터만 수집합니다.

공개 다운로드 서비스로 확장할 때는 개별 파일의 별도 조건·저작자 고지·폰트·포함 이미지 권리를 검토하고, 승인한 버전만 배포 대상으로 관리하는 기능이 추가로 필요합니다. 현재 공개 배포 서버나 승인 화면은 없습니다.

## 첫 실제 실행

2026-09-20, 7개 저장소에서 81개 항목을 발견했습니다. 스크립트 76개와 AE 프리셋 1개를 다운로드했고, 라이선스 불명 프리셋 4개는 링크만 기록했습니다. 다운로드 오류는 0건입니다. 이 수치를 완성 템플릿 81종으로 해석하면 안 됩니다. Premiere/CapCut 네이티브 템플릿은 이번 수집에 없습니다.

소스: TypesettingTools/arch1t3cht-Aegisub-Scripts, lyger/Aegisub_automation_scripts, Akatmks/Akatsumekusa-Aegisub-Scripts, lachrymaLF/Coloramen, rendertom/PseudoEffect, postflows/resolve-title-manager, nelsondooley/after-effects-presets.

## 검증

```sh
PYTHONPATH=packages/pipeline .venv-converter/bin/pytest --noconftest -q \
  tests/test_asset_catalog.py tests/test_interchange.py \
  tests/test_template_factory.py tests/test_motion_templates.py
.venv-converter/bin/ruff check packages/pipeline/pipeline/asset_catalog.py tests/test_asset_catalog.py
```

독립 변환기 테스트이므로 API 서버 의존성을 로드하는 최상위 conftest는 제외합니다. 전체 서버 테스트를 통과했다는 의미가 아닙니다.

영어권 추가 조사와 별도 수집 결과는 [영어 템플릿 소스 조사](ENGLISH_TEMPLATE_SOURCES.md)를 참고하세요.
