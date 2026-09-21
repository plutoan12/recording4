# 이미지 템플릿 자동 제작

사용자가 제공한 이미지 5개를 `.runtime/template-assets`에 원본 그대로 등록했습니다.
24인치 iMac 중복 파일은 하나만 사용합니다. 원본 파일 이름과 SHA-256은 manifest.json에
기록합니다. 사용자 이미지는 Git에 올리지 않습니다.

## 실행

프로젝트 폴더에서 다음 명령으로 자막을 읽어 네 가지 장면을 만듭니다.

```sh
sh scripts/install_converter.sh
sh scripts/make_templates.sh examples/converter-sample.srt .runtime/my-templates --render
```

`--template imac27|imac24|message-board|retro-message|all`로 선택합니다.
`--assets`로 이미지 폴더를 바꿀 수 있습니다. 필요한 파일 이름은
pink.jpg, imac27.png, imac24.png, message-board.jpg, retro-message.jpg입니다.
`--encoding cp949`로 옛 한글 자막을 읽습니다. 기본은 UTF-8/BOM입니다.
`--render`를 빼면 동영상 인코딩 없이 편집/미리보기 파일만 생성합니다.

- imac27 / imac24: 핑크 배경, iMac 프레임, 화면 안 자막.
- message-board: 문자 화면 이미지의 오른쪽 보드에 자막.
- retro-message: 옛 메시지 화면의 파란 말풍선 안에 자막. 작은 영역이라 짧은 문장에 적합.

글꼴 기본값은 이 Mac의 Apple SD Gothic Neo입니다. 다른 OS에서 MP4를 만들 때는
`--font /path/to/korean-font.ttf`로 한글 글꼴을 지정하세요. 폰트는 출력 묶음에 포함하지 않습니다.
AE 스크립트의 폰트 대체 여부는 해당 컴퓨터에서 확인해야 합니다.

## 출력

각 템플릿 폴더에 다음을 생성합니다.

| 파일 | 용도 |
|---|---|
| preview.mp4 | 1920×1080, 30fps, H.264, 무음 영상. --render 지정 시 생성 |
| preview.html | 시간 슬라이더/재생 버튼이 있는 로컬 브라우저 미리보기 |
| build.jsx | AE에서 실행하면 이미지·배경·자막 레이어를 새 컴포지션으로 생성 |
| scene.json | 줄바꿈 적용된 대사, 시각, 이미지 배치, 자막 영역 |
| captions.srt | 다른 편집기에 가져올 수 있는 대사·시간 |
| assets/ | 해당 장면에 사용한 이미지 원본 사본 |

상위 report.json에는 사용한 소재의 해시와 실제 렌더 여부를 기록합니다.
AE는 File → Scripts → Run Script File에서 build.jsx를 실행합니다.
프리미어·캡컷·다빈치에는 preview.mp4를 가져올 수 있습니다.
MP4 자막은 이미 영상에 합쳐져 있으므로 SRT를 함께 올리면 두 겹으로 표시될 수 있습니다.

기존 출력 폴더는 덮어쓰지 않습니다. 새 이름으로 실행하세요. 모든 장면을 성공적으로 만든
뒤에만 최종 폴더를 공개하며 실패한 중간 결과는 정리합니다. 자막이 겹치거나 표시 영역에
너무 길면 자동으로 글자를 버리지 않고 오류를 표시합니다.

## 현재 범위와 검증

이미지+자막으로 4개 장면을 반복 생성하는 1차 자동화입니다. 사용자 동영상을 화면에
자동 삽입하는 옵션, 웹/API 통합, MOGRT 내보내기, CapCut·Fusion 고유 템플릿 생성,
타이핑/등장 애니메이션은 아직 없습니다. AE의 Replaceable screen 레이어를 기준으로
영상 레이어를 직접 배치할 수 있습니다(해당 레이어가 있는 템플릿).
HTML·MP4·AE의 줄바꿈 데이터는 같지만 글꼴 엔진 차이로 픽셀 단위 결과는 다를 수 있습니다.

2026-09-20 확인: 변환/템플릿 테스트 총 41개 통과, 대상 ruff 통과.
4개 6.5초 MP4를 실제 생성하고 FFmpeg 전체 디코딩 성공. 샘플 프레임 육안 확인.
HTML JavaScript와 JSX는 Node 구문 검사 통과(Adobe API 실행 검증과는 다름).
브라우저 도구가 로컬 file URL 열기를 보안 정책으로 차단해 브라우저 상호작용 검증은 하지 못함.
AE와 다른 편집 앱에서 가져오기/렌더링하는 검증도 아직 하지 않음.

```sh
.venv-converter/bin/pytest --noconftest tests/test_interchange.py tests/test_template_factory.py -q
```


외부 자료를 참고해 만든 추가 5종은 [모션 자막 템플릿](MOTION_TEMPLATES.md)을 참고하세요.
