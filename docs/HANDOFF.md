## 2026-09-19: 브라우저 확인·다국어 싱크 실패 조건 추가 (Codex)

- PR #27 후속. 문체 안내/자막 번호/원문 불변을 Chrome 실제 화면에서 확인했습니다. 격리된 테스트 작업이며 영상 재생은 범위 밖입니다.
- 공식 FLEURS 언어별 사람 발화 3개로 en/ja/zh 각각 20개 조건 검사: **영어 0/20, 일본어 0/20, 중국어 20/20**. 기존 한국어 동일 코드 결과는 20/20. 전체 언어 통과로 보고하지 마세요.
- 긴 자막 제한을 늘린 후보는 일본어를 개선했지만 한국어·중국어 회귀로 폐기했습니다. 후보 배포 없이 기존 코드와 이미지 태그를 유지/복구했습니다.
- 최종 Python 399 통과·5 조건부 skip, Ruff 통과. 운영 워커/이미지의 싱크 소스 해시가 저장소와 일치하고 서비스 healthy 확인.
- 신규 `scripts/fetch_fleurs_speech.py`, 출처/해시/현재 결과/폐기 후보 비교를 [보고서](quality/multilingual-sync-2026-09-19/REPORT.md)에 저장했습니다. 실제 현장 영상과 사람 검증 경계, 저음량 대응·신뢰도 판정은 다음 개선 항목입니다.

## 2026-09-19: 원문 말투 유지·조건별 싱크 검증 (Codex)

- [PR #27](https://github.com/plutoan12/recording4/pull/27)에 저장하고 운영 반영 완료. API·워커·관리화면 재빌드/재시작, 전체 서비스 healthy. 기존 18작업 조회에서 3작업에 문체 힌트를 표시했고 데이터 불변 확인. 운영 워커의 새 9문장 WAV 표본 재검증은 원본/2.5초 이동 모두 최대 0.01초, 길이 보존 통과.

- 사용자 선택: 문체를 자동으로 바꾸지 않고 혼용 가능성만 검수 표시.
- 브랜치 `codex/subtitle-style-sync-matrix`, PR #26 위 후속. 담당: pipeline/style_review, API/workflow, WorkflowPanel, worker/analysis, fetch_korean_speech, verify_sync_matrix, 관련 테스트·문서.
- 작업 상세에 문체 종류/자막 번호 안내. 조회는 기존 자막·승인을 변경하지 않음. 인용문 제외 및 제한된 언어별 단서 검사.
- 신규 한국어 사람 목소리 9개로 10종 통제 영상 구성, 이동 0/+2.5초 20검사. 긴 자막 끝이 10초로 잘리는 버그를 발견해 기본 일정 이동 모드에서 길이 보존으로 수정. 같은 기준으로 20/20 통과, 최대 0.50초.
- 399개 테스트 통과, 5개 조건부 skip. TypeScript/Vite/Ruff 통과. 실제 HTTP 확인 완료. 브라우저는 Mac 잠금으로 미확인.
- [상세 범위·결과·재현](quality/style-sync-matrix-2026-09-19/REPORT.md). 통제 영상 검증이며 현장 영상·네 언어 발화 전체를 검증한 것은 아닙니다.

## 2026-09-19: 품질 문제 수정 (Codex)

- [PR #26](https://github.com/plutoan12/recording4/pull/26)에 저장. 최종 API·워커 이미지를 운영 서버에 반영했고 모든 서비스 healthy. 운영 워커에서 숫자/시각·녹화 용어 규칙과 실제 사람 목소리 verify_sync.py(0.5초 기준)를 다시 통과했습니다.

- 브랜치 `codex/subtitle-quality-fixes`. 담당: pipeline/subtitles, worker/providers·analysis·media_tasks, api/config, 관련 테스트와 보고서.
- 숫자/금액/시각 분할 방지, ko/ja의 명시적 녹화 표현→zh 용어 보정. PR #23의 SyncOptions 관련 코드/테스트를 가져와 탐색 제한·입력 검사를 보강했습니다.
- 382개 테스트 통과, 5개 조건부 skip. 실제 음성 보정 최대 오차 0.30초로 기존 0.5초 기준 통과. 실제 번역 두 방향 추가 비용 $0.0040, 녹화 용어 개선 확인.
- [화면 증거·변경 범위·한계](quality/subtitles-2026-09-19/FIXES.md). 전체 문체 통일과 언어별 완전한 의미 단위 분할은 이번 수정 범위 밖입니다.

## 2026-09-19: 실제 다국어 품질 검사 (Codex)

- PR #24 병합 확인, 운영 체크아웃을 main c1c8827로 fast-forward. 이번 변경은 보고서뿐이며 애플리케이션 코드 수정 없음.
- 실제 번역 12방향/48문장, 원음·시각 보존, SRT/VTT, 12개 영상 디코딩 확인. 내부 예산 정산 $0.0279. 결과물은 검수 대기이며 게시하지 않음.
- 발견: 중국어 숫자 중간 줄바꿈, ko/ja→zh 녹화→녹음 용어 오역, 문체 불일치. ffsubsync 실제 음성 보정은 계속 실패; stable-ts는 시작 최대 오차 0.773초로 기존 1초 기준 통과.
- [상세 보고서와 증거](quality/subtitles-2026-09-19/REPORT.md). 무검수 게시 품질 통과로 해석하지 말 것.

## 2026-09-19: 다국어 자막 전용 번역 (Codex)

- PR: https://github.com/plutoan12/recording4/pull/24 . 로컬 운영 서버에 반영 완료(같은 영구 체크아웃). API·worker·dispatcher·monitor·web 재빌드/재시작, 모든 서비스 healthy. 네 언어 실제 FFmpeg 자막 렌더 및 오디오/비디오 디코딩 통과. GitHub Python/Web 검사 통과, 이미지/스택 CI는 기록 시점 진행 중으로 PR은 아직 미병합.

- 브랜치 `codex/multilingual-subtitles`. 담당: WorkflowOptions, workflow_tasks, WorkflowPanel, test_connected_workflow, 관련 문서.
- 자막만 번역 모드와 ko/en/ja/zh 선택을 연결. 원음·원문 시각 유지, 더빙·립싱크 제외, 기존 검수·수정·SRT/VTT·YouTube 트랙 경로 재사용.
- 365개 테스트 통과, 5개 조건부 skip. 네 언어 간 12방향을 공급자 대역으로 검증. TypeScript·Vite build·Ruff 통과. 실제 유료 번역 호출은 하지 않았으며 번역 품질 검증은 남아 있습니다.
- ffsubsync 0.4.27, stable-ts 2.19.1 설치 및 다국어 small 모델 로드 확인. 사람 목소리 싱크 실패는 이번 변경으로 해결되지 않음. PR #23의 별도 싱크 수정과 합치지 않았습니다.
- 기존 PR #20의 자막 전용 모드와 일부 중복되므로 추후 병합 시 중복을 정리해야 합니다. PR #20의 CI 조건 수정과 PR #17·#21의 별도 기능은 포함하지 않습니다.

# 협업 인수인계

## 2026-09-19: API·워커 재빌드 및 자막 표시 방식

`codex/caption-delivery`는 병합된 PR #19 이후 main에서 분리했습니다. 자막 굽기/트랙만 옵션, 언어 지정, 중복 트랙 방지, 트랙 실패 시 예약 중단을 구현했습니다. Docker 이미지 빌드·브라우저 CP949/Shift_JIS 업로드·실제 비공개 YouTube 자막 트랙은 확인했습니다. 사람 목소리 싱크 검증은 실패해 수치와 재현 방법을 [별도 기록](CAPTION_DELIVERY.md)에 남겼습니다. PR #20/#21은 별도 브랜치이며 이번 변경에는 포함하지 않았습니다.

PR #22 병합 후 Mac 운영 배포 완료(`83d94b1`). 자동 시작 경로는 `recording4-caption-delivery` 체크아웃입니다. API/워커 의존성·0006_sync 마이그레이션·트랙 설정 반영 확인. 350개 테스트 통과, 5개 조건부 skip. 실제 운영 싱크 작업은 안전하게 실패하고 대본 보존을 확인했습니다. **남은 품질 문제는 사람 목소리의 자동 싱크 정확도**이며, 실패를 성공으로 처리하거나 측정 기준을 완화하지 않았습니다.

## 2026-09-19: 싱크를 단어 정렬로도 잡을 수 있게 함 (Claude)

- 사용자 요청: 한국어 낭독 싱크 정확도 올리기. 브랜치 `claude/subtitle-file-generation-38xjz4`(최신 main에서 재시작).
- 담당 파일: `services/worker/worker/{analysis,media_tasks}.py`, `services/api/adminapi/{config.py,routers/editing.py}`, `apps/web/src/ClipEditor.tsx`, `scripts/verify_sync_matrix.py`, `.github/workflows/ci.yml`, `tests/{test_editing_api,test_verify_sync_matrix}.py`, `docs/{TECH_DECISIONS,HANDOFF}.md`. 새 의존성 없습니다.

### 왜 설정 조정으로는 더 못 올리는가

Codex의 조건별 측정에서 남은 오차는 **한곳에 몰려 있습니다**: 1.25배 빠른 말 0.50초, 짧은 영상 0.40초, 나머지 8개 조건은 0.00~0.07초. 두 경우 모두 **이동값 하나로는 원리상 못 맞추는** 자리입니다(말 속도가 달라지면 전체를 같은 만큼 밀어서는 맞출 수 없습니다). ffsubsync 설정을 더 돌려도 이 한계는 남습니다.

### 구현한 것

- `worker/analysis.py:realign_subtitles()`: 대본 글자를 그대로 정렬기에 넘겨 **자막마다 시각을 따로** 받습니다. 글자는 건드리지 않고, 자막 개수가 그대로가 아니면 실패로 봅니다. 대본이 실제 발화와 다르면(번역 자막) 여기서 걸립니다.
- `POST .../transcript/sync`에 `method`(`align`|`shift`)와 `language`를 받습니다. 편집기에 버튼 두 개와 차이 설명을 넣었습니다.
- `verify_sync_matrix.py --method both`: **같은 10가지 조건에서 두 방법을 나란히** 잽니다. 손으로 따로 돌려 비교하지 않게 하려는 것입니다.
- CI 워크플로의 `pull_request`에 `labeled`를 넣었습니다. 지금까지는 `verify-align` 라벨을 붙여도 CI가 돌지 않아 의미 없는 커밋을 하나 더 밀어야 했습니다.

### 검증 결과

- `pytest -q`: **405 통과 / 2 skip**(SQLite). `ruff check`·`format --check`, `npm run typecheck`·`build` 통과.
- **정렬 품질 자체는 이 환경에서 재지 못했습니다.** 프록시가 `download.pytorch.org`를 막아 CPU torch를 설치할 수 없고(PyPI 기본 휠은 CUDA 빌드라 `libcudart.so.13`이 없어 못 씁니다), `huggingface.co`도 막혀 한국어 표본을 받지 못합니다. 대역으로 배선만 확인했습니다.

### 남은 작업 — 기본값을 정하려면 이것부터

**기본값은 아직 `shift`입니다.** align이 더 낫다는 근거가 없기 때문입니다. 지금 있는 한국어 숫자는 서로 다른 검사에서 나온 것이라 나란히 둘 수 없습니다(align 0.77/0.08/0.07초는 문장 3개·시작 시각만, shift 최대 0.50초는 조건 10종·시작과 끝 모두). **align의 최악값이 shift의 최악값보다 나쁩니다.**

다음 차례는 한 명령입니다(torch와 Hugging Face가 되는 곳에서):

```
scripts/fetch_korean_speech.py --out /audio --count 9 --offset 30
scripts/verify_sync_matrix.py --directory /audio --out /tmp/matrix --method both
```

그 표를 보고 기본값을 정하면 됩니다. 조건마다 다르면 자동으로 고르게 만드는 것도 선택지입니다(짧은 영상·속도 변화에서만 align).

최종 갱신: 2026-09-19

## 현재 상태

- 사용자 요청: 구조·기술 선택·구현 계획을 문서화하고 Claude와 협업할 수 있도록 GitHub에 저장. 이후 설계 검토를 요청받음.
- 구현 상태: 기본 기반 및 로컬 숏폼 편집·분석 구현. 유료 API·YouTube는 어댑터 단계. 최신 기록은 아래 Codex 오픈소스 통합 항목 참조.
- 저장소: https://github.com/plutoan12/recording4
- 초기에는 README 제목만 있었으며 Codex 작업으로 문서 체계를 추가함.
- 설계 검토에서 발견한 문서 오류·불일치 3건과 설계 공백 R1~R10을 모두 문서에 반영함. 남은 것은 사용자 확정과 측정이 필요한 값뿐임.
- 기술 선택은 추천안. 예산·대상 언어·처리량·모델·배포 서비스는 미확정.

## 완료한 작업

- README를 문서 진입점으로 구성.
- 목표·가정·MVP·확인할 사항 분리.
- 구성도, 처리 단계, 데이터 모델, 승인 버전, 실패 복구 설계 작성.
- 기술 선택 이유 및 공식 참고 문서 정리.
- 단계별 체크리스트와 완료 기준 작성.
- AGENTS.md와 CLAUDE.md로 공통 협업 절차 연결.
- 설계 검토 수행. 수정 이유는 모두 TECH_DECISIONS.md 변경 기록에 남김.
  - 배경음 합성 문장이 원음 전체 혼합과 대사 중복 방지를 동시에 주장하던 모순 정정.
  - `segments`를 `transcript_segments`(원본 소속)와 `translated_segments`(작업 소속)로 분리해 STT 재사용 전제를 데이터 모델에 반영.
  - 제작·게시 상태에 rejected/blocked/failed/cancelled/superseded 추가 및 전이표 명시.
  - 더빙 길이 정합 규칙, 게시 후 수정 경로, 재실행 판정(입력 해시) 구성, 장시간 태스크 규칙, 비용 한도, glossaries·voice_assignments·budgets·budget_reservations 엔터티, 미리보기 서명 URL 발급 주체, 보존·삭제 정책 추가.
  - 사용자 검토 지적 3건 반영: 더빙 구간 겹침 조건, 영상 교체 시 공개 공백, 동시 작업의 예산 초과.
  - IMPLEMENTATION_PLAN.md에 테스트 전략 섹션과 단계별 항목 추가. PROJECT_BRIEF.md 확인 사항에 사용자 확정이 필요한 값 추가.

## 검토 항목 처리 결과

설계 검토에서 제기한 R1~R10을 모두 문서에 반영했습니다. 수치는 제안값이며 아래 "확정이 필요한 값"에서 관리합니다.

| 번호 | 문제 | 처리 | 반영 위치 |
|---|---|---|---|
| R1 | 더빙 길이 정합 정책 부재 | 겹침 금지 조건(다음 구간 시작 시각 침범 금지)을 허용 오차보다 우선하도록 두고 조정 순서·속도 범위·합성 전 겹침 검사 추가 | ARCHITECTURE.md 더빙 길이 정합 |
| R2 | 게시 후 수정 경로 없음 | 메타데이터 수정과 영상 교체를 구분. 이전 영상이 공개 중이면 새 영상의 실제 공개를 확인한 뒤 전환하도록 하고 `superseded`·대체 이력 추가 | ARCHITECTURE.md 게시 후 수정 |
| R3 | 입력 해시 구성 미정 | 공급자·모델·음성·프롬프트·용어집·계약 버전 포함으로 명시 | ARCHITECTURE.md 재실행 판정 |
| R4 | 장시간 Celery 태스크 규칙 없음 | 제출·조회·수거 분리, 감시 전용 태스크, acks_late 규칙 추가 | ARCHITECTURE.md 상태와 복구 |
| R5 | 비용 상한 강제 지점 없음 | `budgets`·`budget_reservations`와 `blocked` 상태 추가. 호출 전 예약(잔액 확인과 예약을 한 트랜잭션에서 수행)과 완료 후 정산, 미정산 예약 만료 회수 | ARCHITECTURE.md 비용 한도 |
| R6 | 용어집·화자 매핑 엔터티 누락 | `glossaries`, `voice_assignments` 추가하고 입력 해시와 연결 | ARCHITECTURE.md 데이터 모델 초안 |
| R7 | 미리보기 서명 URL 발급 주체 불명확 | 구성도를 API 발급으로 수정하고 본문에 명시 | ARCHITECTURE.md 구성, 배포·운영 |
| R8 | YouTube 쿼터가 처리량 가정에 없음 | 제약으로 등록하고 1단계 확인 항목 추가. **수치는 미확인** | TECH_DECISIONS.md, IMPLEMENTATION_PLAN.md 1단계 |
| R9 | 테스트 전략 없음 | 공급자 대체, 전이 테스트, 중복 실행 재현, ffprobe 검사 기준 추가 | IMPLEMENTATION_PLAN.md 테스트 전략 |
| R10 | 삭제 시 파생물 처리 정책 없음 | 보관 기간, 연쇄 삭제, 감사 기록 유지 규칙 추가 | ARCHITECTURE.md 보존과 삭제 |

## 확정이 필요한 값

문서에는 제안값으로 적었습니다. 사용자 확정 또는 대표 영상 측정 후 해당 문서를 갱신합니다.

| 항목 | 현재 문서의 제안값 | 확정 방법 |
|---|---|---|
| 더빙 길이 허용 오차 | ±10% | 대표 영상 측정 |
| 속도 조절 범위 | 0.9~1.15배 | 대표 영상 측정 |
| 축약 재생성 횟수 상한 | 미정 | 대표 영상 측정과 비용 상한 |
| 월·작업당 비용 상한 | 미정. 확정 전 유료 호출은 수동 승인 | 사용자 확정 |
| 원본·중간물·완성본 보관 기간 | 미정 | 사용자 확정 |
| 원본 삭제 시 게시 영상 처리 | 자동 삭제하지 않음 | 사용자 확정 |
| YouTube 일일 쿼터와 업로드 편수 | 미기재 | 공식 문서 직접 확인 |

R8은 이번 세션에서 developers.google.com 접근이 네트워크 정책으로 차단되어 공식 페이지를 열지 못했습니다. 검색 결과에 수치가 있었으나 1차 출처로 확인하지 못해 문서에 옮기지 않았습니다.

## 다음 담당자의 시작점

1. AGENTS.md와 PROJECT_BRIEF.md를 읽고 사용자의 최신 작업 요청을 확인.
2. "확정이 필요한 값" 표에서 사용자 확정 항목(비용 상한, 보관 기간, 삭제 시 게시 영상 처리)을 먼저 질의하고 나머지는 1단계 측정 대상으로 둠.
3. 구현을 요청받으면 IMPLEMENTATION_PLAN.md의 1단계에서 언어·영상량·예산을 확인하고 서비스 접근 필요사항 정리.
4. 작업 브랜치·담당 파일·의존 작업을 아래 기록에 남기고 시작.

## 검증 범위

이번 변경은 Markdown 문서만 대상으로 합니다. 확인한 것은 다음과 같습니다.

- 저장소 내 상대 링크와 필수 문서 존재 여부.
- Markdown 표의 열 수와 헤더 구분자.
- 새로 쓴 상태 이름이 전이표·본문·IMPLEMENTATION_PLAN에서 일치하는지.
- 새 엔터티 이름이 데이터 모델 표와 본문에서 일치하는지.
- 더빙 길이 규칙, 게시 교체 순서, 예산 예약 규칙이 IMPLEMENTATION_PLAN의 체크리스트·테스트 전략과 어긋나지 않는지.

수행하지 않은 검증: API 연결, 영상 품질, 배포, 실제 업로드. Mermaid는 소스 구문만 검토했고 GitHub 화면 렌더링 확인은 별도입니다. R8의 YouTube 쿼터 수치는 공식 문서 접근이 차단되어 확인하지 못했습니다. 더빙 길이 허용 오차와 속도 범위는 측정 근거 없이 제안한 값입니다.

## 작업 기록

| 날짜 | 담당 | 범위 | 결과 / 다음 작업 |
|---|---|---|---|
| 2026-09-18 | Codex | 초기 설계 및 협업 문서 | 설계 문서 작성. 다음은 사용자 지시에 따른 설계 검토 또는 요구사항 확인 |
| 2026-09-18 | Claude | 설계 검토. 브랜치 `claude/claude-md-design-review-v8qdz4`. 담당 파일 docs/ARCHITECTURE.md, docs/TECH_DECISIONS.md, docs/HANDOFF.md | 문서 오류·불일치 3건 수정, 남은 문제 R1~R10 등록 |
| 2026-09-18 | Claude | R1~R10 반영. 같은 브랜치. 담당 파일 docs/ARCHITECTURE.md, docs/IMPLEMENTATION_PLAN.md, docs/PROJECT_BRIEF.md, docs/TECH_DECISIONS.md, docs/HANDOFF.md | 설계 공백 10건을 문서에 반영 |
| 2026-09-18 | Claude | 사용자 검토 지적 반영. PR https://github.com/plutoan12/recording4/pull/1 (main 병합) | 더빙 구간 겹침 조건, 영상 교체 시 공개 공백, 예산 예약·정산 3건 수정. 다음은 "확정이 필요한 값" 질의와 1단계 측정 |
| 2026-09-18 | Claude | 2단계 기본 기반 구현. PR https://github.com/plutoan12/recording4/pull/2 (main 병합, 21d905f). 담당 파일은 아래 후속 기록 참조 | API·워커·관리화면·마이그레이션·CI 추가. CI(PostgreSQL)에서 테스트 118개 통과. 다음은 실제 S3·FFmpeg 연동 확인과 3단계 |

향후 기록에는 브랜치·커밋 또는 PR 링크, 변경 파일, 실제 검증 결과, 미해결 문제를 포함합니다. 완료되지 않은 항목은 완료로 표시하지 않습니다.

## Codex 후속: 숏폼 편집 추가 (2026-09-18)

- 사용자 요청: 롱폼을 숏폼으로 바꾸는 편집 기능 추가. 기존 문서화 범위에서 설계·구현 계획에 반영함.
- 통합 기준: Claude의 PR #1과 후속 수정 ff17e8c가 병합된 main(a642cf8). 해당 변경을 보존하고 숏폼 문서를 후속 커밋으로 추가함.
- 추가 문서: SHORT_FORM_EDITING.md. 함께 갱신: README, PROJECT_BRIEF, ARCHITECTURE, IMPLEMENTATION_PLAN, TECH_DECISIONS, HANDOFF.
- 기능: 하이라이트 추천/수동 구간 선택, 세로 크롭·패딩, 자막·제목 편집, 원어 또는 선택 구간 더빙, 다수 숏폼의 독립된 승인·예약.
- 현재 구현 없음. 문서 상대 링크·코드 펜스 및 git diff 공백 검사 수행. API·영상·브라우저 실행 검증은 수행하지 않음.
- 동시 협업 변경 확인: Claude가 ff17e8c에서 구간 겹침 금지, 새 영상 실제 공개 후 기존 영상 전환, 동시 호출 예산 예약·정산을 문서에 반영함. 숏폼 변경을 최신 main 위에 통합함. 구현 검증은 아직 수행하지 않음.
- 다음 작업: 사용자 요청에 따라 구현 단계 진행. 숏폼 기본 길이·개수·추천 모델은 구현 전 확인 또는 샘플 평가 대상.

## Claude 후속: 2단계 기본 기반 구현 (2026-09-18)

- 사용자 요청: 추가된 설계 내용을 반영해 필요한 코드를 구현. 범위는 사용자 선택으로 [구현 계획](IMPLEMENTATION_PLAN.md) 2단계(기본 기반)로 한정함.
- 통합 기준: Codex의 숏폼 편집 문서가 병합된 main(6ab6156). 문서는 고치지 않고 코드만 추가함. 단 README·IMPLEMENTATION_PLAN·TECH_DECISIONS는 실제 상태를 반영해 갱신함.
- 담당 파일: `pyproject.toml`, `alembic.ini`, `packages/pipeline/**`, `services/api/**`, `services/worker/**`, `migrations/**`, `tests/**`, `apps/web/**`, `infra/**`, `.github/workflows/ci.yml`, `docs/DEVELOPMENT.md`.

### 구현한 것

- 공유 도메인 패키지 `pipeline`: 상태 전이표(제작·게시·단계 실행), 입력 해시, 예산 계산 규칙. 설계 문서의 표를 그대로 옮겼습니다.
- 관리 API: 로그인(JWT), 원본 업로드 URL 발급·완료 검증·미리보기 URL, 작업 생성·목록·조회·전이. 서명 URL은 API만 발급합니다.
- 워커: ffprobe 기반 원본 검사 태스크, outbox 디스패처, Celery 설정(acks_late, prefetch 1, 큐 분리).
- DB: 17개 테이블 마이그레이션. 롱폼 엔터티와 숏폼 엔터티(clip_candidates, clip_edits, clip_ranges)를 함께 만들었습니다. `render_jobs`는 stage_runs 통합 여부가 미확정이라 만들지 않았습니다.
- 예산 예약·정산: 잔액 확인과 예약을 한 트랜잭션에서 수행하고 예산 행을 잠급니다.
- 관리화면: 로그인, 원본 등록(저장소 직접 업로드), 원본·작업 목록, 작업 생성.
- 개발 환경: Docker Compose(PostgreSQL, Redis, MinIO, API, 워커, 디스패처), CI(린트·포맷·마이그레이션 왕복·테스트·프런트엔드 빌드).

### 구현 중 발견해 고친 것

- 상태 컬럼을 `String`으로 두면 DB에서 읽을 때 평범한 문자열이 되어 전이표 조회가 TypeError로 깨졌습니다. `Enum(native_enum=False)`로 바꿨습니다.
- 업로드 크기 불일치로 거부할 때 예외가 요청 트랜잭션을 롤백해 거부 사유가 저장되지 않았습니다. 사유를 먼저 확정한 뒤 예외를 던지도록 고쳤습니다.

### 검증 결과

PR https://github.com/plutoan12/recording4/pull/2 (main 병합, merge commit 21d905f). 커밋 3f7971f(구현), e0da671(CI 수정).

작업 환경(SQLite)에서 수행:

- `pytest -q`: 117개 통과, 1개 건너뜀. 동시 예약 경합 테스트는 행 잠금이 필요해 PostgreSQL 전용이며 이 환경에는 Docker 데몬이 없어 건너뛰었습니다.
- `ruff check .`, `ruff format --check .`: 통과.
- `alembic upgrade head` → `downgrade base` → `upgrade head`: SQLite에서 통과.
- 프런트엔드 `tsc -b --noEmit`, `vite build`: 통과.

CI(GitHub Actions, PostgreSQL 16 서비스)에서 수행:

- `pytest -q`: **118개 통과, 건너뛴 항목 없음.** 동시 예약 경합 테스트가 실제 행 잠금 위에서 실행되어, 한도 10에 2씩 8개를 동시에 요청하면 5개만 예약되고 3개가 거부되는 것을 확인했습니다.
- 마이그레이션 왕복: PostgreSQL에서 통과(`Context impl PostgresqlImpl`).
- 린트·포맷·프런트엔드 타입 검사·빌드: 통과.

첫 CI 실행은 실패했습니다. 테스트가 `from tests.conftest import ...`로 conftest를 모듈처럼 불러와, 현재 디렉터리를 `sys.path`에 넣어주는 `python -m pytest`에서는 통과하고 CI의 `pytest`에서는 수집이 깨졌습니다. 픽스처로 바꿔 해결했습니다(e0da671). 앞으로 로컬 검증은 CI와 같은 `pytest` 명령으로 수행합니다.

수행하지 못한 검증: 실제 S3·MinIO 연동, 실제 FFmpeg 실행, Docker Compose 기동, 브라우저 화면 확인. 이 환경에는 Docker 데몬과 ffprobe가 없습니다. 저장소와 ffprobe는 테스트에서 대역으로 바꿨습니다.

### 남은 문제와 다음 작업

- 실제 S3·FFmpeg·Compose 기동 검증이 남았습니다. 개발 환경에서 한 번 돌려봐야 합니다.
- `job.start` outbox 주제에 연결된 태스크가 없습니다. 3단계에서 파이프라인 단계를 붙일 때 연결합니다.
- 관리자 계정 생성은 수동 스크립트입니다. 화면이 필요하면 별도 작업입니다.
- `render_jobs` 엔터티와 숏폼 편집 API·화면은 3A단계입니다.
- "확정이 필요한 값"(비용 상한, 보관 기간, 삭제 정책, 더빙 허용 오차)은 그대로 열려 있습니다. budgets 테이블은 만들었지만 실제 한도 값은 사용자 확정 후 넣습니다.

## Codex 후속: 오픈소스 영상 기능 통합 (2026-09-18)

- 사용자 요청: GitHub에서 필요한 기능의 코드를 찾아 프로젝트에 추가. 구현 범위가 문서화에서 실제 코드로 확대됨.
- 기준: main 21d905f. 작업 브랜치 `codex/video-pipeline-integrations`. Claude의 기존 기반 코드를 보존해 확장함.
- 작업 파일: pipeline/editing.py, worker의 analysis/rendering/media_tasks/providers/youtube/cli, editing API, MediaTask 모델·0002 마이그레이션, ClipEditor.tsx, 저장소·큐·Docker·CI 설정, 테스트와 라이선스·실행 문서.
- 오픈소스: faster-whisper, PySceneDetect, pysubs2, FFmpeg, Google 공식 SDK. 버전은 pyproject.toml에 고정하고 출처·라이선스 문서를 추가함.
- API/워커 흐름: 원본 → 대본/STT/장면 → 구간·크롭·자막 → 렌더 요청 → S3 결과물 → 버전 승인. 원본 시각과 출력 시각을 분리하며 동일 큐 메시지의 중복 실행을 원자적 점유로 방지함.
- 유료 공급자·YouTube는 호출 가능한 어댑터이며 자동 파이프라인 연결은 아직 아님. 실제 서비스 호출 없이 계약 테스트를 수행함.
- 검증: Python 138개 통과/로컬 PostgreSQL 전용 1개 skip, 실제 FFmpeg 합성·디코딩·음성 검사, 장면 감지 실행, SQLite 마이그레이션 왕복, TS 타입 검사·빌드, 브라우저 테스트 계정 로그인·원본 미리보기·구간 입력·렌더 요청 확인.
- 실제 STT 추론·유료 API·OAuth·업로드·Compose 전체 기동·실제 S3는 미검증. 자동 얼굴 추적·LLM 추천·유료 전체 파이프라인·게시 UI는 남아 있음.
- 다음 담당자는 [오픈소스 통합](OPEN_SOURCE_INTEGRATIONS.md)의 실행 및 미구현 범위를 먼저 읽을 것. provider 어댑터를 job.start와 연결하기 전에 예산 예약, 실패/응답 유실 복구, 승인된 파일 체크섬 및 publication 체크포인트 저장을 구현할 것.


## Codex 후속: 단계별 실행 연결 (2026-09-18)

- 사용자 요청: “단계별로 연결해줘.” 기존 PR #4 위에 제작·게시 오케스트레이션을 연결함. 이전 기록의 “어댑터까지만 구현” 상태를 대체함.
- 신규 0003_workflow 마이그레이션, 제작 단계 체크포인트·실행 점유·지연 outbox, 이중 예산 예약/정산, 불명확한 호출 수동 확인, FFmpeg 더빙 타이밍·합성, 승인 기반 YouTube 게시 워커, OAuth 연결 CLI, 관리화면을 추가함.
- 수동 start/complete/approve 전이를 막고 실제 단계 완료 및 결과물 승인 API로만 상태를 변경함. 테스트도 실제 워커 경로를 검증하도록 변경함.
- 로컬 검증: Python 146개 통과/1개 PostgreSQL 전용 skip, 실제 FFmpeg 합성·디코딩, SQLite 마이그레이션 왕복, ruff, 프런트엔드 타입·빌드, 브라우저 로그인→제작 요청→실제 워커 처리→검수 필요 표시 확인.
- 실제 STT 추론·유료 공급자·OAuth·업로드·S3·Compose 전체 기동은 미검증. 모든 외부 공급자 테스트는 대역 사용. 자동 얼굴 추적·음원 분리·LLM 하이라이트 추천은 미구현.
- 다음 담당자는 [CONNECTED_WORKFLOW.md](CONNECTED_WORKFLOW.md)를 먼저 읽고 서버별 인증/가격 상한/예산을 설정한 뒤 비공개 샘플을 검증할 것. 업로드 결과 불명확 상태를 임의 초기화하지 말 것.


## Codex 후속: Mac 운영 자동화 (2026-09-18)

- 사용자는 PR 검토·병합과 전체 운영 자동화를 요청한 뒤, 이 Mac에서 먼저 가동하고 유료 처리는 설정 후 시작하도록 선택함.
- `infra/compose.runtime.yml`, Caddy 관리화면, `scripts/ops.py`와 `smoke.py`, 관리자/버킷 초기화, 자동 점검·만료 작업 재큐잉, DB·미디어 백업·복원 검증, 로그인 시 자동 시작을 추가함. 로컬 주소는 http://localhost:18444. 영구 경로는 `/Users/an-youwon/Projects/recording4`.
- 실제 PostgreSQL·Redis·MinIO·FFmpeg 워커와 관리화면을 기동. 실제 S3 업로드→ffprobe 검사→큐→세로 렌더→다운로드/디코딩 성공. 무료 합성 내레이션으로 faster-whisper 모델 추론→자막 합성→검수 대기 성공.
- 발견/수정: Docker Hub MinIO 이미지 다운로드 실패→공식 Quay 경로, 호스트 포트 충돌→전용 18444 포트, 워커 내부 원본 검사 URL 분리, ffprobe 오류의 서명 URL 노출 방지, STT 모델 캐시 권한 수정. 캐시 실패 작업의 재개 성공도 확인함.
- DB 및 영상 백업 생성, 별도 임시 DB의 실제 복원·조회 검증 후 임시 DB만 삭제. 로그인 LaunchAgent `com.recording4.stack` 등록. 비밀은 `.runtime`에만 저장하고 Git/이미지에서 제외함.
- 로컬 Python 151 통과/1 PostgreSQL 전용 skip. 실제 유료 번역·더빙·립싱크와 YouTube OAuth·업로드는 실행하지 않음. 실제 비용 한도·음성·계정 연결은 다음 설정 단계.
- Claude 데스크톱의 기존 recording4 세션에 ff725de 기준 PR #4 독립 리뷰를 요청함. 리뷰 및 병합 결과는 후속 기록 참조.
- 운영 안내: [LOCAL_OPERATIONS.md](LOCAL_OPERATIONS.md). 외부 HTTPS 도메인, 외부 알림 수신처, 기기 외부 백업과 보관/삭제 기간은 미설정. 원본·백업 자동 삭제는 하지 않음.


## Codex·Claude 검토 및 운영 최종 검증 (2026-09-18)

- Claude 데스크톱의 독립 리뷰에서 립싱크 종결 실패의 재개 불가, 타임존 변환, 수정 문장 TTS 재사용 누락을 확인했고 PR #4의 `7b4db34`에서 수정함. 상태 전이·예약 만료 관측·음원 보존/실제 비용 문서도 정정함. 후속 재검토는 요청했으나 Mac 화면 잠금으로 답변 확인 전이며, Claude의 최종 승인을 받았다고 간주하지 않음.
- 로컬 Python 160 통과/2 PostgreSQL 전용 skip, ruff 및 관리화면 빌드 통과. PR #4의 정확한 수정 커밋에 대한 GitHub Python·관리화면 CI 모두 통과. 실제 PostgreSQL의 Asia/Seoul 시간도 UTC로 정상 변환 확인.
- 수정 후 실제 내레이션 영상으로 업로드→원본 검사→로컬 STT→숏폼 렌더→검수 대기→다운로드/디코딩 재검증 성공. 유료 호출 0, YouTube 업로드 0.
- 최종 점검: DB·Redis·S3·워커 정상, 실패/차단 작업·만료 실행 점유·outbox 오류 0. DB 백업 및 미디어 7개 스냅샷 생성, 별도 DB 복원 후 작업 3개 조회 성공.
- 로그인 자동 시작은 실제 kickstart 실행 종료 코드 0 확인. 백그라운드 Docker 자격증명 도우미 대기를 피하도록 프로젝트 전용 공개 이미지 클라이언트 설정을 사용하며, 사용자 Docker 인증 설정은 보존함.
- 실행 위치 `/Users/an-youwon/Projects/recording4`, 관리화면 http://localhost:18444, 비공개 로그인 파일 `.runtime/LOGIN.txt`. Mac 로그인 시 시작하며 Mac이 꺼지거나 잠자면 처리할 수 없음.
- 다음 설정: 공급자 키·음성·월/건별 예산, YouTube OAuth, 필요시 도메인/HTTPS·외부 알림·기기 외부 백업·보관/삭제 정책. 유료 처리와 YouTube 업로드는 계속 비활성화. 실제 공급자/YouTube 전체 검증은 이 설정 후 수행해야 함.


## 무료 모드·YouTube 계정 연결 (2026-09-18)

- 사용자가 무료 기능만 사용하도록 선택했으므로 유료 번역·더빙·립싱크는 비활성화 유지. 원어 음성, 로컬 STT, 숏폼·자막·렌더 기능 사용 가능.
- 사용자 승인 후 YouTube Data API 활성화, recording4 OAuth 앱 및 Mac 데스크톱 클라이언트 생성, 본인 테스트 사용자 등록과 명시적 OAuth 동의 완료.
- 인증 JSON과 토큰은 Git에서 제외되는 `.runtime/provider-secrets`에 권한 0600으로 저장. 실행 토큰은 Docker `provider_secrets` 볼륨에 UID 10001/0600으로 설치하고 워커에 읽기 전용 마운트. 서버 환경에 인증 파일 경로·채널 ID 적용 및 YouTube 실행 활성화. 비밀·개인 계정 식별자는 이 기록에 포함하지 않음.
- 실제 워커에서 토큰 갱신 및 연결 채널 조회 성공. 전체 컨테이너 Healthy. 실제 영상 업로드·예약 공개는 수행하지 않았으며 결과물별 검수·승인을 유지함.
- OAuth 앱은 테스트 상태이므로 YouTube 범위의 refresh token은 7일 후 만료됨. 장기 무인 운영에는 Google 앱 게시 준비와 재인증이 필요. [Google 토큰 만료 문서](https://developers.google.com/identity/protocols/oauth2#expiration). 현재 연결을 영구 인증으로 오인하지 말 것.


## 유료 처리 허용 및 예산 상한 (2026-09-18)

- 사용자가 무료 모드 선택을 변경하여 유료 번역·더빙을 허용하고 월 10 USD·영상 작업 1건 1 USD를 승인함. 이 기록이 앞선 무료 모드 방침을 대체함.
- 실제 환경에 유료 처리 허용, `R4_MAX_JOB_BUDGET_USD=1`, `R4_MAX_MONTHLY_BUDGET_USD=10` 적용. 이번 달 공통 예산 10 USD 저장(사용액/예약액 0).
- DB/화면의 예산이 더 크더라도 예약 시 서버 상한과 저장 한도 중 작은 값을 적용하도록 보완. 누적 사용액과 미정산 예약을 포함하며 기존 작업에도 적용. 예산·연결 워크플로 테스트 24 통과/1 skip, ruff 통과.
- Google 번역 자격증명과 ElevenLabs 계정/API 키·음성·계약 단가는 아직 미설정. 허용 플래그만으로 실제 번역·더빙이 준비됐다고 간주하지 말 것. 공급자 호출/유료 결제는 아직 수행하지 않음.
- 상한은 파이프라인이 예약하는 설정 단가 기반 금액이며 공급자의 구독료·세금·외부 사용액을 자동 포함하지 않음. 별도 구독이 필요한 경우 월 총액에 포함해 잔여 예산을 조정해야 함.


## 번역 인증 연결·더빙 가입 완료 (2026-09-18)

- 사용자 동의 후 Cloud Translation API 활성화, 기존 recording4 데스크톱 OAuth 앱에 cloud-translation 범위만 추가로 인증. 번역 토큰을 별도 google-adc.json으로 비공개 저장하고 워커의 읽기 전용 비밀 볼륨에 설치함.
- Google 프로젝트·ADC 경로와 NMT 단가 0.02 USD/1,000자 설정 적용. 실제 워커 지원 언어 조회 성공(196개), 텍스트 번역 호출은 아직 0. OAuth 테스트 모드의 7일 만료 제한은 동일하게 적용됨.
- ElevenLabs는 사용자 약관·성인 확인 후 Google 가입 및 초기 설정 완료. Starter 월 6 USD(세금/수수료 별도) 결제 화면까지 준비. 정기 구독 승인과 결제수단 확인 대기 중이며 결제·API 키 발급·음성 생성은 아직 하지 않음.
- 구독 승인 후 월 총예산 10 USD에 구독료/세금을 먼저 반영하고 나머지 범위에서 파이프라인 예산을 조정할 것. 월 10 USD 전체를 추가 사용료로 허용하면 안 됨.


## ElevenLabs 연결 및 실제 유료 샘플 검증 (2026-09-18)

- 사용자 승인 후 Starter 구독 활성화 확인. 월 기본 6 USD, 다음 청구 표시 6.60 USD, 갱신일 10월 18일. 자동 충전 Off 유지. 월 총 10 USD에서 구독·세금 6.60 USD를 제외해 서버 월 상한과 이번 달 DB 예산을 3.40 USD로 축소했고 작업당 1 USD 유지. 카드 환전/수수료 및 서비스 외부 사용액은 자동 집계되지 않음.
- 사용자가 제한 API 키 생성·로컬 저장 승인. recording4-local-tts 키에 TTS와 Voices Read만 허용, 갱신 주기당 15,000크레딧 한도, 유출 자동 차단 On. 비공개 파일 0600 및 실행 환경에 저장; Git에 키를 넣지 않음.
- 실제 워커 음성 목록 조회 200 확인. 기본 제공 George 음성(`JBFqnCBsd6RMkjVDRZzb`), eleven_multilingual_v2 사용. TTS 예약 단가는 구독·세금/30,000크레딧 기준 보수적 0.22 USD/1,000자. 구독 차감 뒤에도 TTS를 예산에 반영하므로 포함 크레딧에 대한 보수적 이중 계산이며 추가 청구 실측치가 아님.
- 짧은 한국어 제공 대본 → 실제 Google 영어 번역 → 실제 ElevenLabs 음성 생성 → 음성 합성 → 세로 숏폼 렌더 → 검수 대기 성공. 최종 MP4 다운로드 및 FFmpeg 전체 디코딩 성공. 번역/TTS 각각 1회, 재시도 없음, 설정 단가 기준 합계 0.0120 USD. 이 검증은 제공 대본 사용이며 STT 실추론은 앞선 무료 샘플에서 별도 검증함.
- 로컬 결과 `.runtime/paid-smoke-final.mp4`, 상세 보고 `.runtime/paid-smoke-report.json`. 영상·비밀·개인 로그는 Git 제외. 실제 YouTube 업로드/예약은 아직 0이며 결과물별 승인 필요.
- 남은 작업: 사용자의 실제 영상/음성 품질 검수, 승인 결과물 비공개 업로드·예약 검증, Google 테스트 OAuth 7일 만료 대응, 필요시 외부 도메인/알림/오프사이트 백업/보관 정책.


## 실제 YouTube 비공개 업로드 검증 (2026-09-18)

- 사용자 계속 진행 요청에 따라 기존 6초 합성 샘플을 기술 검수함. H.264 360×640, AAC 48kHz, 6.000초 확인. 3초 프레임의 제목·영어 자막 표시 확인 및 로컬 Whisper로 음성을 역전사해 번역 대본과 일치 확인. 자연스러움에 대한 사용자 청취 검수는 별도임.
- 해당 결과물 버전만 승인 API로 승인하고, 승인 ID·채널·SHA-256 검증 후 기존 resumable upload 어댑터로 실제 비공개 업로드 1회 성공. YouTube processed/succeeded, privacyStatus private, publishAt 없음 확인.
- 현재 게시 API는 공개 예약 시각을 필수로 요구하므로 이번 비공개 검증은 독립 운영 스크립트로 수행함. DB Publication 행은 생성하지 않았으며 예약 워커 전체 경로를 검증했다고 간주하지 말 것. 중복 방지 체크포인트는 비공개 객체 저장소 ops/private-upload-test/ 아래에 보존함. 같은 결과물을 관리화면에서 새 게시 요청하면 별도 업로드가 될 수 있으므로 기존 영상의 예약 검증 시 이 체크포인트·영상 ID를 재사용할 것.
- 영상 ID와 승인 ID는 로컬 .runtime/private-upload-report.json, 처리 상태는 .runtime/private-upload-status.json에 보관. 공개 저장소에는 계정별 영상 링크를 기록하지 않음.
- 수동 DB 백업과 미디어 13개 스냅샷 완료. 사용자가 테스트 샘플 비공개 유지·실제 영상으로 예약을 선택함. 실제 영상 경로, 공개 시각(한국시간), 대상 언어 입력 대기. 샘플에 공개 예약을 설정하지 말 것.


## YouTube 링크 → MP4 원본 가져오기 (2026-09-18)

- 사용자 요청에 따라 관리화면 링크 입력, 인증 API, outbox/워커 다운로드, 비공개 객체 저장, 기존 ffprobe 검사, 원본 다운로드 버튼까지 연결함. Mac 서버에 배포 완료. 사용법은 CONNECTED_WORKFLOW.md 참조.
- yt-dlp 2026.8.19와 Node 22를 워커에 설치. YouTube 단일 공개 링크만 허용하며, 최대 720p H.264 영상·M4A 음성을 FFmpeg로 MP4 병합. 통합 MP4만 요구하면 실제 공개 영상에서 형식 없음 오류가 발생하는 점을 확인해 분리 스트림 병합으로 보완함.
- 최종/입력 파일 각각 최대 500MB, 다운로드·병합 10분 제한. 임시 디스크 작업당 최대 약 1.5GB 필요. 시간 초과 시 Node·FFmpeg를 포함한 프로세스 그룹 종료. 자격증명 환경변수·브라우저 쿠키를 다운로더에 전달하지 않음. 가져오기만으로 번역·더빙·공개 예약을 실행하지 않음.
- 실제 Blender 공개 샘플 https://www.youtube.com/watch?v=aqz-KE-bpKQ 로 API 등록→outbox→다운로드→병합→MinIO→ffprobe 검증 성공: 1280×720, 634.625초, 161,192,090바이트, verified. 서명 다운로드 HTTP 206 및 MP4 ftyp 확인. 비공개 영상은 rejected, 내부 URL 입력은 HTTP 422 확인. 상세 결과는 Git 제외 .runtime/link-import-smoke-report.json.
- 전체 Python 검사 173 통과/5 skip 후 프로세스 그룹 종료 테스트를 추가하고 관련 28개 재통과. ruff 린트·포맷, TypeScript/Vite 빌드 통과. 실제 Mac 컨테이너 모두 Healthy. 사이트 변경·로그인/지역 제한·지원 형식 부재는 여전히 실패할 수 있음.
- 사용자의 SNL 링크에 대한 한국어 자막·더빙 없음 요청은 별도 미완료. 해당 영상은 이번 기술 검증에서 내려받거나 번역하지 않음. 기존 6초 테스트 업로드는 비공개 유지, 실제 영상 예약도 아직 설정하지 않음. 요청 공개 시각은 2026-09-19 02:00 Asia/Seoul이며 시각이 지나면 새 시각 확인 필요.


## 자막 라이브러리 `[subtitles]` extra 등록 (2026-09-18)

- 사용자 요청: 자막 관련 오픈소스를 더 찾아 설치. 조사 후 stable-ts·WhisperX·kss를 선택하고 의존성과 라이선스만 등록함. 브랜치 `claude/claude-md-design-review-v8qdz4`(PR #3 병합 후 최신 main에서 재시작).
- 담당 파일: `pyproject.toml`, `docs/OPEN_SOURCE_INTEGRATIONS.md`, `third_party/licenses/{stable-ts,whisperX,kss}.txt`, `docs/HANDOFF.md`.
- **코드는 연결하지 않았습니다.** `analysis.py`·`rendering.py`·워커 Dockerfile 모두 그대로입니다. 사용하는 코드가 없는 상태에서 워커 이미지를 수 GB 키우지 않기 위해서입니다.

### 도입 이유와 대상 빈틈

| 빈틈 | 현재 상태 | 대응 후보 |
|---|---|---|
| 단어 단위 타이밍 폐기 | `analysis.py`가 `word_timestamps=True`로 받아 문장 단위만 저장 | stable-ts, WhisperX |
| 타이밍 없는 대본 등록 불가 | `PUT /source-assets/{id}/transcript`가 클라이언트에 start/end 요구 | stable-ts `align()` |
| 자막 길이·가독성 검사 없음 | CPS·줄 길이 규칙 없음. libass 자동 줄바꿈에 위임 | stable-ts `split_by_*`, kss |
| 화자 정보 없음 | `voice_assignments` 스키마는 있으나 채울 수단 없음 | WhisperX 화자 분리(pyannote 게이트 모델·HF 토큰 필요) |

SRT/VTT 내보내기는 이미 쓰는 pysubs2로 가능하므로 새 의존성을 넣지 않았습니다.

### 검증 결과

- `pip install '.[analysis,subtitles]'` 성공, `pip check` 이상 없음. 리눅스 x86-64 / Python 3.11.
- 프로젝트 고정값 유지 확인: SQLAlchemy 2.0.36, alembic 1.14.0, faster-whisper 1.2.1, httpx 0.28.1, pysubs2 1.8.0.
- 앱 모듈과 신규 라이브러리 동시 임포트 확인. kss 한국어 문장 분리 실행 확인.
- 설치량 8.4GB(기본 인덱스, 대부분 nvidia CUDA 휠). whisperx가 torch를 2.8.0으로 고정.
- **미검증**: CPU 전용 설치(`download.pytorch.org` 차단으로 실행 불가), 실제 정렬·화자 분리 품질, Mac/Docker 설치, 모델 가중치 다운로드.

### 남은 문제와 다음 작업

- CPU 전용 설치 명령을 실제 Mac 환경에서 한 번 확인해야 합니다. 문서의 명령은 미검증입니다.
- WhisperX 화자 분리는 pyannote 게이트 모델 약관 동의와 HuggingFace 토큰이 필요합니다. 토큰 보관 위치를 정해야 합니다.
- kss 정확도를 올리려면 `python-mecab-ko`가 추가로 필요합니다.
- 코드 연결 시 워커 Dockerfile과 CI 설치 시간·이미지 크기를 함께 검토해야 합니다.

## 자막 정렬·표시 규칙 연결 (2026-09-18)

- 사용자 요청: `[subtitles]`로 설치한 라이브러리를 실제 코드에 연결. 브랜치 `claude/claude-md-design-review-v8qdz4`(PR #6에 이어서 커밋).
- 담당 파일: `packages/pipeline/pipeline/subtitles.py`(신규), `services/worker/worker/{analysis,media_tasks,rendering,composition,workflow_tasks,subtitle_rules}.py`, `services/api/adminapi/{config.py,models.py,routers/editing.py}`, `migrations/versions/0004_align_media_task.py`, `apps/web/src/ClipEditor.tsx`, 테스트 2개.
- **Codex 작업과 겹칠 수 있는 파일**: `media_tasks.py`, `rendering.py`, `composition.py`, `workflow_tasks.py`, `routers/editing.py`. PR #5 진행 중이면 병합 순서를 조정해야 합니다.

### 구현한 것

- `pipeline/subtitles.py`: 순수 표시 규칙. 줄바꿈, 문장·어절 경계 분할, 시간 비례 배분, 가독성 검사. 외부 의존성 없이 동작하고 kss가 있으면 문장 분리에 씁니다.
- `align_text()`와 `align` MediaTask 종류: 타이밍 없는 대본을 원본 음성에 정렬해 새 대본 버전 생성. 마이그레이션 `0004_align`으로 `kind` 제약 확장.
- `POST /source-assets/{id}/align`, `GET /source-assets/{id}/subtitle-check`, `PUT /transcript` 응답에 `violations` 추가.
- 렌더·합성 경로가 규칙을 적용합니다. libass 자동 줄바꿈에 맡기지 않습니다.
- 관리화면: 대본 붙여넣기·정렬 요청, 가독성 검사 결과 표시.

### 설계 판단

- 초당 글자수는 자막을 나눠도 줄지 않으므로 분할 기준이 아니라 **보고 항목**입니다.
- 나눌 시간이 모자라면 나누지 않고 그대로 둔 뒤 보고합니다. 읽을 수 없이 짧은 자막을 만들지 않습니다.
- 어떤 경로에서도 글자를 자동으로 버리거나 줄이지 않습니다.

### 검증 결과

- `pytest -q`: 198 통과 / 5 skip. 새 테스트 25개(`test_subtitles.py` 18, `test_align_api.py` 7).
- `write_subtitles`가 만든 실제 ASS 파일에서 분할과 `\N` 줄바꿈 확인.
- 마이그레이션 `0004_align` SQLite 왕복 통과. `ruff check`·`format --check` 통과. TypeScript 타입 검사·Vite 빌드 통과.
- **미검증**: 실제 stable-ts 정렬 품질과 모델 다운로드, PostgreSQL에서의 `0004` 적용(CI 대상), 실제 FFmpeg 렌더에서의 자막 가독성, 한국어 기본값의 화면 적정성.

### 남은 작업

- WhisperX는 여전히 미사용입니다. 화자 분리로 `voice_assignments`를 채우는 작업이 남아 있습니다.
- 자막 기본값(줄 길이 20자·2줄·20 CPS)은 측정 근거가 없는 제안값입니다.
- 워커 이미지에 `[subtitles]`와 CPU 전용 PyTorch를 추가했습니다. 작업 환경에는 Docker 데몬이 없고 `download.pytorch.org`가 차단되어 빌드를 돌릴 수 없었으므로, CI에 **워커 이미지 빌드 잡**을 추가해 거기서 검증합니다. 잡은 이미지를 빌드하고 컨테이너 안에서 `torch.__version__`에 `+cpu`가 들어 있는지와 워커 모듈 임포트를 확인합니다. PR과 main에서만 돌아갑니다.
- Dockerfile의 torch 고정값은 whisperx 요구 범위와 연동됩니다. whisperx를 올릴 때 함께 고치지 않으면 빌드가 실패합니다.


## 자막 표시 규칙에 표준 근거 적용 (2026-09-18)

- 사용자 요청: 자막 관련 코드를 더 조사하고, 필요한 것은 설치하고 참고할 것은 반영. 브랜치 `claude/claude-md-design-review-v8qdz4`(PR #7).
- 담당 파일: `packages/pipeline/pipeline/subtitles.py`, `services/api/adminapi/config.py`, `tests/test_subtitles.py`, `docs/{ARCHITECTURE,OPEN_SOURCE_INTEGRATIONS,TECH_DECISIONS,HANDOFF}.md`, `.github/workflows/ci.yml`.
- 의존 작업: 없음. 새 런타임 의존성을 추가하지 않았습니다.

### 반영한 것

- 길이 단위를 글자 폭으로 변경(`text_width()`). 한글 1자, 라틴·숫자·공백·문장부호 0.5자. 줄바꿈·분할·CPS 검사가 모두 이 값을 씁니다.
- 기본값을 Netflix 한국어 자막 지침(성인물)에 맞춤: 줄당 16자, 2줄, 초당 14자, 최대 7초. 최소 표시 시간은 1초로 유지(지침 5/6초보다 보수적).
- 근거와 출처, 반영하지 않은 규칙을 `docs/OPEN_SOURCE_INTEGRATIONS.md`에 기록.

### 설치 판단

- **새로 설치한 런타임 의존성 없음**. ffsubsync는 쓸 자리가 없고, silero-vad는 faster-whisper 내장 VAD를 `transcribe()`에서 이미 쓰고 있습니다. subaligner·NeMo는 설치량이 CPU 전용 결정과 어긋납니다. 근거는 오픈소스 통합 문서에 남겼습니다.
- 개발 환경에만 kss 6.0.6을 설치해 문장 분리 경로를 처음으로 실제 실행 확인했습니다(그전에는 구두점 대체 경로만 돌았습니다).

### 검증 결과

- `pytest -q`: 204 통과 / 5 skip. kss 설치 전후 모두 동일.
- `ruff check`, `ruff format --check` 통과.
- CI(`5c139cc`) 세 잡 모두 성공. 워커 이미지 **4.66GB**, API 이미지 256MB, 컨테이너 안 `torch 2.8.0+cpu` 확인.

### 남은 문제

- 기본값은 OTT 번역 자막 기준입니다. 숏폼 세로 화면에서의 적정성은 여전히 측정하지 않았습니다.
- 구·절 단위 줄 나눔 미구현. 두 줄로 끊길 때 어절 경계까지만 맞춥니다.
- WhisperX는 여전히 미사용입니다(화자 분리 → `voice_assignments`).
- 실제 stable-ts 정렬 품질과 모델 다운로드는 미검증입니다.
- Netflix 지침 원문 페이지는 이그레스 정책으로 직접 열지 못했습니다. 검색 결과 스니펫으로 확인한 값입니다.


## 남은 문제 해소: 근거·측정·화자 분리 (2026-09-18)

- 사용자 요청: 남겨 둔 세 가지(숏폼 화면 적정성 미측정, Netflix 원문 미확인, WhisperX 미사용·정렬 품질 미검증)를 해결. 브랜치 `claude/claude-md-design-review-v8qdz4`(PR #7).
- 담당 파일: `packages/pipeline/pipeline/speakers.py`(신규), `services/worker/worker/{analysis,media_tasks}.py`, `services/api/adminapi/{config,models}.py`, `services/api/adminapi/routers/{editing,jobs}.py`, `migrations/versions/0005_diarize_media_task.py`(신규), `scripts/{measure_subtitles,make_speech_sample,verify_align}.py`(신규), `.github/workflows/ci.yml`, 테스트 2개.

### 1. 원문 확인 → 기본값 정정

검색 도구의 서버 측 조회로 Netflix 한국어 지침 본문을 확인했습니다(원문 페이지 직접 접근은 이그레스 정책이 막습니다). **제가 넣은 14자/초가 틀렸습니다.** I.15(일반 번역 자막)는 성인 12자/초, 아동 9자/초이고, 14/11은 II.3 SDH에서만 허용하는 상향값입니다. 기본값을 12자/초로 내렸습니다. 줄당 16자와 0.5자 계산, 2줄, 5/6초·7초는 확인한 값과 같습니다.

### 2. 숏폼 화면 적정성 → CI 실측

`scripts/measure_subtitles.py`가 워커 이미지 안에서 1080x1920 프레임에 자막을 그리고 FFmpeg cropdetect로 글자 픽셀 상자를 잽니다. 기본 줄 길이 16자가 좌우 여백(쓸 수 있는 폭 980px) 안에 한 줄로 들어가지 않으면 CI가 실패합니다. 추정이 아니라 libass 렌더 결과입니다.

### 3. WhisperX 화자 분리 연결

- `worker/analysis.py:diarize()` — WhisperX `DiarizationPipeline`. 토큰이 없으면 모델을 내려받기 전에 막습니다.
- `pipeline/speakers.py` — 겹친 시간이 가장 긴 화자를 자막에 붙이는 순수 규칙. 겹치는 화자가 없으면 비워 둡니다.
- `diarize` MediaTask 종류(마이그레이션 `0005_diarize`) — 대본 글자는 그대로 두고 화자만 붙인 새 버전을 만듭니다.
- API — `POST /source-assets/{id}/diarize`, `GET /source-assets/{id}/speakers`, `GET·PUT /jobs/{id}/voice-assignments`.
- 워커 이미지 안에서 `DiarizationPipeline` 진입점이 실제로 있는지 CI가 확인합니다.

### 4. 정렬 품질 검증

`scripts/make_speech_sample.py`가 espeak-ng로 문장 사이 1초 무음을 넣은 한국어 음성을 만들어 문장 시작 시각을 확정하고, `scripts/verify_align.py`가 같은 대본을 타이밍 없이 정렬해 오차를 잽니다. 글자 변형·자막 겹침·문장 시작 오차 3초 초과면 실패합니다. 모델을 실제로 내려받으므로 PR `verify-align` 라벨이나 커밋 메시지 `[verify-align]`이 있을 때만 돌립니다.

### 검증 결과

- `pytest -q`: 221 통과 / 5 skip. 새 테스트 17개(`test_speakers.py` 7, `test_diarize_api.py` 10).
- `ruff check`, `ruff format --check` 통과. 마이그레이션 `0005` SQLite 왕복 통과.

### 실측 결과 (CI `cdd4c5a`, 세 잡 모두 성공)

- 자막 화면: 글자 크기 64에서 한글 16자는 **647px**(화면 폭의 60%), 여백 980px 안에 한 줄. **24자까지** 들어갑니다(26자 1054px로 넘음). 한 줄 높이 41px. 전에 "20자까지"라고 적은 것은 측정 표가 20자에서 끝났기 때문이지 한계가 아니었습니다.
- 정렬(whisper small): 문장 경계 3/3개를 자막 경계로 찾음. 오차는 자막 1 **0.00초**, 자막 2 0.01초, 자막 3 0.00초.
- 이미지: 워커 4.66GB, API 256MB, `torch 2.8.0+cpu`.

### 남은 한계

- 자막 시각 오차는 합성 음성 기준 0.01초입니다. **실제 사람 목소리에서도 같은지는 미확인입니다.**
- **실제 pyannote 화자 분리 추론은 아직 돌려 보지 못했습니다.** 게이트 모델 토큰이 필요합니다. 코드 경로와 진입점만 확인한 상태입니다.
- 정렬 검증은 합성 음성 기준입니다. 사람 목소리 품질을 대신하지 않습니다.
- 자막 줄 나눔은 여전히 어절 경계까지만 맞춥니다. 구·절 단위는 미구현입니다.
- 화자 분리 결과를 쓰는 관리화면은 아직 없습니다. API까지만 열려 있습니다.


## 자막 시각 정확도 추적 (2026-09-18)

- 사용자 요청: 첫 자막이 1초 늦게 시작하는 문제를 줄일 것. 브랜치 `claude/claude-md-design-review-v8qdz4`(PR #7).
- 담당 파일: `packages/pipeline/pipeline/alignment.py`(신규), `services/worker/worker/analysis.py`, `scripts/{make_speech_sample,verify_align}.py`, `.github/workflows/ci.yml`, `tests/test_alignment.py`(신규).

### 원인 두 가지

같은 음성에 설정을 바꿔 가며 재서 좁혔습니다. 무음 보정과 VAD는 영향이 없었습니다.

| 원인 | 증상 | 처리 |
|---|---|---|
| 정렬기의 줄 유지 옵션(`original_split`) | 첫 자막 **1.00초 지연** (옵션 켬 2.00초, 끔 0.98초, 실제 1.00초) | 옵션을 버리고 단어 시각으로 직접 줄을 나눔(`cues_for_lines`) |
| 단어 시각이 무음 안쪽으로 당겨짐 | 마지막 자막 **1.73초 선행** (tiny·small 동일) | 자막 시작을 발화 시작에 맞춤(`snap_starts`) |

### 결과 (CI `bd42bf2`, whisper small)

자막 1 오차 0.00초, 자막 2 0.01초, 자막 3 0.00초. 문장 경계 3/3개 유지.

### 판단 기록

- 검증 모델을 `tiny`에서 운영 기본값 `small`로 바꿨습니다. 쓰지도 않는 모델의 오차를 재고 있었습니다.
- `snap_starts`는 옮겨도 되는 경우만 옮깁니다. 앞 자막 침범, 자막 소멸, 2초 밖 발화 시작은 건드리지 않습니다. 각각 테스트로 고정했습니다.
- 줄 묶기는 맞출 수 없으면 포기하고 정렬기 구간을 그대로 씁니다. 글자가 바뀌거나 단어가 줄 경계를 넘으면 포기합니다.

### 남은 한계

- 합성 음성(espeak) 기준입니다. 사람 목소리 실측은 아래 「사람 목소리 정렬 실측과 발화 구간 문제」 절에 있습니다.
- 화자 분리(pyannote) 실제 추론은 게이트 모델 토큰이 없어 미검증입니다.


## 사람 목소리·실제 화자 분리 검증 연결 (2026-09-18)

- 사용자 요청: 남은 두 한계(합성 음성 기준 정확도, pyannote 실추론 미검증)를 처리. 브랜치 `claude/claude-md-design-review-v8qdz4`(PR #7).
- 담당 파일: `scripts/{speech_sample,fetch_korean_speech,make_speech_sample,make_two_speaker_sample,verify_diarize}.py`, `.github/workflows/ci.yml`, 문서.

### 한 것

- `speech_sample.py`로 음성 묶음 만드는 공통 도구를 분리했습니다. 합성 음성과 사람 목소리가 같은 형식(sample.wav + expected.json)을 만들어 같은 검증기가 읽습니다.
- `fetch_korean_speech.py`: 공개 한국어 낭독 음성을 datasets-server에서 받아 검증용 음성을 만듭니다. CI가 합성 음성 검사에 이어 사람 목소리 검사를 한 번 더 돌립니다.
- `make_two_speaker_sample.py`: 서로 다른 두 목소리를 번갈아 넣고 조각마다 정답 화자를 기록합니다. 사람 목소리 조각이 있으면 한쪽 화자로 씁니다.
- `verify_diarize.py`: pyannote를 실제로 돌려 화자가 둘 이상 갈리는지, 정답 화자별로 결과가 한 표시로 몰리는지 확인합니다.
- CI: 사람 목소리 검사는 `verify-align` 라벨로, 화자 분리 검사는 저장소 시크릿 `HF_TOKEN`으로 켜집니다. 단계 `if`에서는 `secrets` 컨텍스트를 못 쓰므로 잡 수준 env로 받아 `env.HF_TOKEN != ''`로 판정합니다.

### 사용자 조치가 필요한 것

**화자 분리 실검증은 `HF_TOKEN` 시크릿 없이는 돌지 않습니다.** 제가 대신 만들 수 없는 값입니다.

1. https://huggingface.co/pyannote/speaker-diarization-3.1 에서 약관에 동의합니다.
2. 같은 계정에서 읽기 토큰을 발급합니다.
3. 저장소 Settings → Secrets and variables → Actions에 `HF_TOKEN`으로 넣습니다.

시크릿이 없으면 이 단계는 건너뛰고 나머지는 그대로 돕니다.

### 남은 한계

- 사람 목소리 검증은 네트워크로 공개 데이터셋을 받습니다. 이 작업 환경에서는 `huggingface.co`와 `openslr.org`가 모두 막혀 있어 **CI에서만 확인됩니다**. 데이터셋 주소나 응답 형식이 바뀌면 그 단계가 실패합니다.
- 화자 분리의 정확도(경계 오차 등)는 재지 않습니다. 화자가 갈리는지만 봅니다.


## 로컬(VS Code)에서 이어서 하기 (2026-09-18)

클라우드 세션에서 하던 작업을 로컬로 옮깁니다. 코드와 상태는 모두 브랜치와 이 문서에 있습니다.

```bash
git clone https://github.com/plutoan12/recording4.git
cd recording4
git checkout claude/claude-md-design-review-v8qdz4   # PR #7
pip install -e ".[dev]"
pytest -q && ruff check . && ruff format --check .
```

### 로컬에서 하면 빨라지는 것

클라우드 세션은 Docker 데몬이 없고 `huggingface.co`·`download.pytorch.org`·`openslr.org`가 모두 막혀 있어, 아래를 전부 CI로 보내고 한 번에 6분씩 기다렸습니다. 로컬에서는 바로 돌아갑니다.

```bash
# 워커 이미지 (4.66GB, 첫 빌드는 오래 걸립니다)
docker build -f infra/Dockerfile.worker -t recording4-worker:local .

# 자막이 세로 화면 여백 안에 들어가는지 실측
docker run --rm -v "$PWD/scripts:/work:ro" --entrypoint python \
  recording4-worker:local /work/measure_subtitles.py

# 합성 음성으로 정렬 정확도 측정
sudo apt-get install -y espeak-ng ffmpeg   # macOS: brew install espeak-ng ffmpeg
python3 scripts/make_speech_sample.py --out /tmp/align
docker run --rm -v /tmp/align:/audio -v "$PWD/scripts:/work:ro" \
  --entrypoint python recording4-worker:local /work/verify_align.py \
  --directory /audio --model small

# 사람 목소리로 같은 측정 (공개 데이터셋을 내려받습니다)
python3 scripts/fetch_korean_speech.py --out /tmp/human --count 3
docker run --rm -v /tmp/human:/audio -v "$PWD/scripts:/work:ro" \
  --entrypoint python recording4-worker:local /work/verify_align.py \
  --directory /audio --model small
```

**`fetch_korean_speech.py`는 클라우드에서 한 번도 실행하지 못했습니다.** 네트워크가 막혀 CI에서만 처음 돌아갑니다. datasets-server 응답 형식이 가정과 다르면 여기서 실패하니, 로컬에서 먼저 돌려 보는 편이 빠릅니다.

### 토큰이 있어야 되는 것

화자 분리(pyannote)는 게이트 모델입니다. 환경을 옮겨도 토큰 없이는 못 돌립니다.

1. https://huggingface.co/pyannote/speaker-diarization-3.1 약관 동의
2. 같은 계정에서 읽기 토큰 발급
3. 로컬은 `R4_HF_TOKEN`, CI는 저장소 시크릿 `HF_TOKEN`

```bash
python3 scripts/make_two_speaker_sample.py --out /tmp/two --human /tmp/human
docker run --rm -v /tmp/two:/audio -v "$PWD/scripts:/work:ro" \
  -e R4_HF_TOKEN --entrypoint python recording4-worker:local \
  /work/verify_diarize.py --directory /audio --max-speakers 2
```

### 같은 브랜치를 두 곳에서 밀지 않기

클라우드 세션이 PR #7을 감시하며 CI 실패를 고쳐 왔습니다. 로컬에서 같은 브랜치에 커밋한다면 한쪽만 푸시해야 충돌이 없습니다.


## 사람 목소리 정렬 실측과 발화 구간 문제 (2026-09-18)

- 사용자 요청: 첫 자막 지연을 줄이고 정렬을 다시 검증할 것. 브랜치 `claude/claude-md-design-review-v8qdz4`(PR #7).
- 담당 파일: `packages/pipeline/pipeline/alignment.py`, `services/worker/worker/analysis.py`, `scripts/{speech_sample,verify_align}.py`, `tests/test_alignment.py`.

### 고친 것 두 가지

| 어긋난 곳 | 증상 | 처리 |
|---|---|---|
| VAD `min_silence_duration_ms` 기본 2000ms | 문장 사이 1초 쉼이 무시돼 **18초 음성 전체가 발화 구간 1개**(0.99~18.06). 맞출 시작점이 없어 자막 2·3이 1.57·1.71초 밀린 채 남음 | 200ms로 낮춰 문장마다 끊고, 조각은 `merge_spans(0.3)`이 다시 합침 |
| 정답 앞 무음을 -40dB 고정 문턱으로 측정 | 실내 잡음이 문턱보다 커서 잡음 시작을 말 시작으로 기록(2번 조각 0.08초 기록, 실제 1.65초) | 조각마다 최대 음량 -35dB로 문턱을 다시 잡고, 고정 문턱 값도 함께 기록 |

설정은 `supported_options()`가 이름별로 걸러 넘깁니다. 이전에는 `TypeError`를 통째로 잡아 설정이 하나도 안 걸린 채 기본값으로 돌아갔고, 위 첫 번째 원인이 거기 가려져 있었습니다.

### 검증 결과 (CI `09bbe82`, whisper small, 전 단계 초록)

| 음성 | 자막 1 | 자막 2 | 자막 3 | 문장 경계 |
|---|---|---|---|---|
| 합성(espeak) | 0.01초 | 0.05초 | 0.02초 | 3/3 |
| 사람 목소리(zeroth-korean) | **0.77초** | 0.08초 | 0.07초 | 3/3 |

이전 값은 합성 1.71초, 사람 목소리 1.65초였습니다. 판정 한계는 1.0초입니다.

### 이 수치의 한계

- zeroth-korean에는 단어 시각 정답이 없습니다. "실제 시작"은 우리가 에너지(FFmpeg)로 재는 값이고, 자막 시작은 Silero VAD가 찾는 값입니다. 서로 다른 방법이라 맞아떨어지는 것은 교차 확인이 되지만, **외부 정답으로 잰 정확도는 아닙니다.**
- 남은 0.77초가 정렬이 늦은 것인지 정답이 이른 것인지 이 방법으로는 가리지 못합니다. 단어 시각이 있는 한국어 공개 데이터가 필요합니다.
- 문턱을 바꾸면 정답이 움직이므로, 고정 -40dB로 잰 값을 `expected.json`(`lead_silence_at_40db`)과 로그에 함께 남깁니다. 이번에 실제로 움직인 것은 세 조각 중 하나였습니다(0.08 → 1.65초).
- 화자 분리(pyannote) 실추론은 `HF_TOKEN` 시크릿이 없어 여전히 미검증입니다. 절차는 위 절을 보세요.


## 스택 전체 기동·실제 S3·전사 품질 실측 (2026-09-19)

- 사용자 요청: 자막 끝 시각 검증 → Compose 전체 기동 → 실제 S3/MinIO → 실제 STT 전사 품질 → 게시 경로 실측을 차례대로. 브랜치 `claude/claude-md-design-review-v8qdz4`(PR #7).
- 담당 파일: `.github/workflows/ci.yml`, `scripts/{verify_align,verify_transcribe}.py`, `tests/test_verify_{align,transcribe}.py`.

### 1. 자막 끝 시각 (CI `055be31`, whisper small)

시작만 재던 검증에 끝을 넣었습니다. 끝의 정답은 시작만큼 또렷하지 않아서(말끝 숨소리·잔향) **정답과의 차이는 찍기만** 하고, 판정은 자막이 지켜야 할 것으로 합니다.

사람 목소리 실측:

| 자막 | 정렬 끝 | 정답 끝 | 차이 | 표시 시간 |
|---|---|---|---|---|
| 1 | 10.52초 | 11.93초 | 1.41초 | 8.66초 |
| 2 | 20.54초 | 21.75초 | 1.21초 | 5.88초 |
| 3 | 31.44초 | 33.18초 | 1.74초 | 7.92초 |

세 번 다 자막이 정답보다 **이르게** 끝납니다. 방향이 일정한 것이 단서입니다. 같은 구간의 VAD 발화 끝은 10.46 / 20.29 / 31.71초로, 자막 끝과 0.06~0.27초 차이입니다. 즉 정렬과 VAD는 서로 맞고 에너지 문턱으로 잰 정답 끝만 늦습니다. 말끝 뒤에 남는 숨소리와 잔향이 문턱을 넘기 때문입니다. 자막은 말이 끝나는 지점에서 사라지고 있습니다.

판정 결과: 다음 문장 침범 없음, 표시 규칙 적용 뒤 줄 수·겹침 위반 없음. 규칙 적용 뒤 자막은 3개 → 7개로 나뉘고 읽기 속도는 6.8~7.3자/초로 한도(12자/초) 안입니다.

**이 검사에서 버그가 하나 나왔습니다.** 0.99초에 시작하는 자막이 1.00초 문장을 정확히 맞춘 것인데, "자막 시작보다 뒤에 시작하는 문장"을 다음 문장으로 보다가 자기 문장에 걸렸습니다. 순서가 아니라 가까움으로 자기 문장을 고르게 고쳤고, 한 자막이 두 문장을 담은 경우도 침범이 아니게 했습니다. 두 경우 모두 테스트로 고정했습니다.

### 2·3. Compose 전체 기동과 실제 S3/MinIO (CI `7b565b4`, 첫 시도 통과)

CI 잡 `스택 기동 검증`이 **운영에서 쓰는 구성**(`compose.runtime.yml`)을 그대로 띄웁니다. 개발용(`docker-compose.yml`)이 아닙니다.

- 컨테이너 9개: postgres·redis·minio(healthy), api(healthy), worker(celery, healthy), dispatcher, monitor, backup, web(caddy). 기동 3분 21초.
- `scripts/smoke.py`로 전 경로 8초: 로그인 → 원본 생성 → **실제 S3 PUT**(Caddy `/recording4/*` → MinIO, presigned URL) → 검증 → 제작(transcribe·render 단계 succeeded) → 결과물 내려받기 → FFmpeg 디코딩.
- 결과: `state=review_required`, `paid_calls=0`, `youtube_uploads=0`.

이 작업 환경에는 Docker **데몬**이 없어(CLI만 있음) 직접 띄울 수 없습니다. CI가 대신합니다.

### 4. 실제 STT 전사 품질 (CI `055be31`, whisper small, 사람 목소리)

| 문장 | CER | 어긋난 곳 |
|---|---|---|
| 1 | 3.9% | 삼 월 → 3월, 장동련 → 장동연 |
| 2 | 11.8% | 겹쳐 → 격쳐, 한창 → 한참, 폭 파묻혀 버렸다 → 폭파무차버렸다 |
| 3 | 14.3% | 오픈해 → 오픈에, 이천 십 팔 년 → 2018년, 진행돼 왔다 → 진행되어왔다 |

**전체 CER 9.7%** (원문 134자). 한계는 첫 실측을 보고 35% → **20%**로 내렸습니다. 품질 목표가 아니라 회귀 감시용 상한입니다. 표본이 세 문장뿐이고 데이터셋 행이 바뀌면 값도 움직이므로 실측의 두 배로 둡니다.

숫자 표기 차이(이천 십 팔 년 ↔ 2018년)가 CER을 올립니다. 문장 3의 14.3% 중 상당 부분이 그것입니다. 다만 문장 2는 진짜 오인식입니다. 수치만 보지 말고 문장별 비교를 봐야 하는 이유입니다.

### 남은 것

- **게시 경로 실측(YouTube 비공개 업로드)은 아직입니다.** 실제 계정에 영상이 올라가고 API 할당량을 쓰므로 사용자 확인 뒤에 합니다.
- 화자 분리(pyannote) 실추론은 `HF_TOKEN` 시크릿이 없어 여전히 미검증입니다.
- 전사 품질은 낭독 음성 세 문장 기준입니다. 잡음·대화체·여러 화자는 재지 않았습니다.

### 5. 게시 경로 (2026-09-19)

사용자가 "대역 검증 + 로컬 실행 절차서"를 선택했습니다. 실제 업로드는 하지 않았습니다.

- **대역 검증을 한 겹 더 넣었습니다.** 지금까지 업로드 경로는 Google SDK를 통째로 대역으로 바꿔서만 검증했습니다. 정작 위험한 곳은 SDK와 주고받는 재개 규약인데(`docs/OPEN_SOURCE_INTEGRATIONS.md`에 "SDK 버전 변경 시 재개 계약 테스트를 다시 실행"하라고 적혀 있습니다) 그 테스트가 없었습니다. `tests/test_youtube_resumable.py`가 **실제 SDK**를 로컬 가짜 YouTube 서버에 붙여 돌립니다: 세션 재사용(중단 후 재개해도 세션 1개), 저장한 오프셋을 믿지 않고 서버에 다시 묻기, 완료된 업로드 재시도 안 함, 승인본이 다르면 네트워크 전에 중단. 계정도 네트워크도 쓰지 않습니다.
- 쓰면서 알게 된 것: 재개 업로드의 "아직 안 끝났다"는 308인데, SDK가 `build_http()`에서 308을 리다이렉트 목록에서 빼 둡니다. 맨 `httplib2.Http()`를 넘기면 httplib2가 리다이렉트로 처리해 실패합니다. 서비스를 직접 만들어 쓰는 코드가 생기면 여기를 봐야 합니다.
- CI `파이썬 검사`가 `[dev,providers]`로 설치합니다. google-api-python-client는 torch를 끌어오지 않아 가볍습니다.
- 실제 업로드 절차는 [게시 경로 실행 절차](PUBLISH_RUNBOOK.md)에 있습니다. OAuth 인증 파일은 계정 소유자의 컴퓨터에만 둡니다. 클라우드 세션이나 CI 시크릿에 갱신 토큰을 올리면 그 토큰으로 계정 영상을 올리고 지울 수 있습니다.


## 토큰 없는 화자 분리 공급자 (2026-09-19)

- 사용자 요청: `HF_TOKEN`을 받을 수 없으니 게이트가 아닌 모델로 화자 분리를 검증할 것. PR #7 병합(`17b2010`) 이후 `main`에서 브랜치를 새로 땄습니다.
- 담당 파일: `packages/pipeline/pipeline/speakers.py`, `services/worker/worker/analysis.py`, `scripts/verify_diarize.py`, `.github/workflows/ci.yml`, `pyproject.toml`, `tests/test_speakers.py`.

### 한 것

`analysis.diarize_by_embedding()`: 발화 구간을 이미 쓰는 VAD로 찾고, 겹치는 창(1.5초, 0.75초 간격)으로 잘라 창마다 목소리 특징(`speechbrain/spkrec-ecapa-voxceleb`, 공개 모델)을 뽑은 뒤 코사인 거리로 묶습니다. 토큰도 약관 동의도 필요 없습니다.

묶는 규칙은 `pipeline/speakers.py`의 순수 계산으로 뺐습니다. 모델 없이 테스트할 수 있습니다.

- `windows()`: 한 발화 구간 안에서 화자가 바뀔 수 있습니다. 통째로 한 목소리로 보면 그 경계를 영영 못 찾습니다. 창을 겹쳐 잘라 경계가 창 한가운데 걸려도 이웃 창이 온전한 목소리를 담게 합니다.
- `cluster()`: 코사인 k-평균. **시작점을 무작위로 고르지 않습니다.** 무작위면 같은 음성을 두 번 재도 답이 달라져 검증에 쓸 수 없습니다. 이미 고른 점에서 가장 먼 점을 차례로 잡습니다.
- `turns_from_labels()`: 같은 화자의 이웃 창을 잇습니다. 겹쳐 자른 부분은 이어 붙이면서 자연히 사라집니다.

CI는 이 공급자로 화자 분리를 **시크릿 없이 매번** 검증합니다(`화자 분리 검증 (토큰 없는 공급자)`). pyannote 단계는 `HF_TOKEN`이 있을 때만 그대로 돕니다.

### 검증 결과 (CI `1bff963`)

음성 30.17초, 정답 네 조각(A 사람 목소리 2, B espeak 2)을 번갈아 넣은 것입니다.

| 정답 | 정답 구간 | 찾은 구간 | 표시 |
|---|---|---|---|
| A | 1.08~11.93초 | 1.86~10.46초 | SPEAKER_00 |
| B | 12.93~15.45초 | 12.96~15.20초 | SPEAKER_01 |
| A | 18.10~25.27초 | 18.18~23.81초 | SPEAKER_00 |
| B | 26.27~29.17초 | 26.30~28.90초 | SPEAKER_01 |

문장 4개 모두 정답 화자와 맞는 표시를 받았고, 정답 화자별로 표시가 하나로 몰렸습니다(A→SPEAKER_00, B→SPEAKER_01). 서로 다른 두 표시입니다.

시작은 0.03~0.78초 차이입니다. 끝은 1.2~1.5초 이르게 끝나는데(사람 목소리 조각), 자막 끝 시각에서 본 것과 같은 현상입니다. 말끝 숨소리·잔향이 정답 끝을 늦춥니다.

**이 실측을 찾아낸 부수 효과**: 두 화자 음성이 29초가 아니라 1초로 묶이고 있었습니다. concat 목록에 파일 이름만 적어서 다른 폴더의 사람 목소리 조각을 찾지 못했고, ffmpeg는 그 조각을 빼고도 성공으로 끝냈습니다. 절대 경로로 적고 묶은 뒤 길이를 확인하게 고쳤습니다(`speech_sample.concat_listing`). 이 결함은 두 화자 음성을 만든 때부터 있었지만 pyannote 검증이 토큰이 없어 한 번도 돌지 않아 드러나지 않았습니다.

### 이것이 검증하는 것과 하지 않는 것

검증합니다: 우리 쪽 묶기·배정 규칙이 실제 음성에서 동작하는지, 서로 다른 두 목소리가 실제로 갈리는지, 정답 화자별로 결과가 한 표시로 몰리는지.

**검증하지 않습니다: pyannote.** 둘은 다른 모델입니다. 토큰 없는 공급자가 통과했다고 운영 기본값이 검증된 것이 아닙니다. 스크립트가 어느 공급자로 쟀는지 항상 출력하고, embedding으로 통과하면 그 줄을 따로 찍습니다.

### 이 공급자의 한계

- 겹쳐 말하는 구간을 다루지 못합니다. 한 창은 한 화자로만 묶입니다.
- 화자 수를 스스로 세지 않습니다. `speakers`로 알려 줘야 합니다. 검증 스크립트는 정답의 화자 수를 씁니다.
- 목소리가 비슷하면 갈리지 않습니다. 품질을 pyannote와 같게 볼 근거가 없습니다.
- 그래서 **기본 공급자가 아닙니다.** 운영 경로(`diarize()`)는 그대로 pyannote이고, 이쪽은 토큰이 없을 때의 선택지입니다.


## 자격증명이 필요한 두 가지를 위한 준비 (2026-09-19)

- 사용자 요청: 남은 두 가지(pyannote 실추론, 실제 게시)도 해 둘 것. 토큰과 OAuth 인증은 사람이 계정으로 만들어야 하는 값이라 제가 만들 수 없습니다. 대신 **그 값을 넣는 순간 막히지 않도록** 남은 부분을 처리했습니다.
- 담당 파일: `services/worker/worker/analysis.py`, `scripts/preflight_publish.py`(신규), `.github/workflows/ci.yml`, `docs/PUBLISH_RUNBOOK.md`, `tests/test_preflight_publish.py`(신규).

### pyannote: 토큰을 넣고도 막히는 지점을 먼저 막았습니다

토큰이 있어도 약관 동의가 빠지면 pyannote는 예외 대신 **빈 모델**을 돌려줍니다. 그러면 한참 뒤 `AttributeError: NoneType ...`로 터져서 무엇이 잘못됐는지 알 수 없습니다. 실제로 사람이 막히는 곳이 여기입니다.

`diarize()`가 모델을 못 불러온 경우를 잡아, 동의가 필요한 **두 페이지를 모두** 짚어 주는 말로 바꿉니다(`speaker-diarization-3.1`과 `segmentation-3.0`). 한쪽만 동의하고 실패하는 경우가 흔합니다.

CI가 토큰 없이도 이 경로를 점검합니다(`화자 분리 토큰 오류 안내 점검`): 잘못된 토큰으로 불러 보고, 안내에 두 주소가 모두 있는지 확인합니다. 통과해 버리면 점검이 헛도는 것이므로 그것도 실패로 봅니다.

### 게시: 올리기 전 점검기

`scripts/preflight_publish.py`가 업로드 직전까지 확인하고 **영상은 올리지 않습니다**. 실행 설정, 갱신 토큰, 업로드 권한, 인증 파일 권한, 그리고 **설정한 채널과 계정 채널이 같은지**를 봅니다. 마지막 것이 핵심입니다. 다르면 승인한 것과 다른 채널에 올라가고 되돌릴 수 없습니다.

판단 규칙은 순수 함수로 빼서 테스트했습니다. 네트워크 호출은 읽기 한 번(`channels.list`)뿐입니다.

### 점검이 찾아낸 진짜 결함 두 가지 (CI `a18fd3d`)

1. **토큰이 있어도 화자 분리는 시작조차 못 했습니다.** `DiarizationPipeline.__init__() got an unexpected keyword argument 'use_auth_token'`. 설치된 whisperx(pyannote.audio 4.x)는 그 인자를 받지 않습니다. 토큰이 없어 한 번도 돌지 않아 드러나지 않았습니다. 이제 이 버전이 받는 이름만 골라 넘깁니다(`diarization_arguments`). VAD 설정에서 쓴 방식과 같습니다.

2. **동의해야 할 모델 페이지가 문서와 달랐습니다.** 실제로 받으러 가는 모델은 `pyannote/speaker-diarization-community-1`입니다(`speaker-diarization-3.1`이 아닙니다). 3.1에서만 동의하면 증상이 그대로입니다. 코드가 실행 시점에 모델 이름을 찾아 안내 맨 앞에 넣고, CI가 그 이름을 찍습니다.

### 여전히 사람이 해야 하는 것

- **HF 토큰**: huggingface.co 로그인 → **`pyannote/speaker-diarization-community-1`** 페이지에서 약관 동의(안내에 함께 뜨는 페이지도 확인) → 읽기 토큰 발급 → 저장소 시크릿 `HF_TOKEN`. 계정이 필요한 일이라 대신할 수 없습니다.
- **실제 게시**: `docs/PUBLISH_RUNBOOK.md` 순서대로. 2.5단계 점검을 먼저 돌리면 업로드 전에 대부분의 실패가 드러납니다.


## 한국어 → 영어 번역 확인과 언어별 자막 규칙 (2026-09-19)

- 사용자 질문: "한글에서 영어로도 번역이 잘 돼?" → 확인해 보니 경로는 돌지만 품질은 잰 적이 없고, 자막 규칙이 한국어 기준이라 영어 결과물에 어긋나 있었습니다. 둘 다 처리했습니다.
- 담당 파일: `packages/pipeline/pipeline/subtitles.py`, `services/worker/worker/{subtitle_rules,workflow_tasks}.py`, `scripts/{verify_translate,measure_subtitles}.py`, `docs/TRANSLATION_CHECK.md`(신규), `docs/samples/ko-en.json`(신규), `.github/workflows/ci.yml`.

### 1. 자막 규칙이 한국어 기준이었습니다

기본값은 Netflix 한국어 지침(줄당 16자, 초당 12자)이고 폭은 한글 1자·라틴 0.5자로 셉니다. 영어 자막에 그대로 쓰면 줄당 32자(지침 42자), 초당 24자(지침 20자)가 됩니다. 줄은 필요 이상으로 짧게 쪼개지고 읽기 속도 검사는 오히려 느슨해집니다.

`LANGUAGE_RULES`에 언어별 값을 폭 단위로 담고 렌더가 자막 언어로 규칙을 고릅니다.

**영어 줄 길이는 지침이 아니라 실측에서 나왔습니다.** 지침 42자는 가로 화면 기준이고 우리는 세로 숏폼(1080px)에 글자 크기 64를 씁니다. CI가 **한도를 꽉 채운 한 줄**(알파벳 38자)을 실제로 렌더해 좌우 여백 980px 안에 들어가는지 봅니다. 읽기 속도는 지침대로 초당 20자(폭 10.0)입니다. 한국어에서 지침 16자를 측정 안에서 쓴 것과 같은 방식입니다. 번역한 자막이면 목표 언어, 원본 대본 그대로면 원본 언어로 규칙을 고릅니다.

**실측(2026-09-19 CI, 글자 크기 64, 여백 980px):** 한도를 채운 줄(알파벳 38자, 폭 19.0)이 **859px**(88%), 실제 문장 `In March last year a colleague of the`(폭 18.5)이 **729px**(74%)입니다. 가장 넓은 글자 M만 반복하면 **26자까지**(926px)이고 28자는 996px로 넘습니다. 그래서 **전부 대문자인 줄은 38자 한도에서 넘칩니다.** 숫자를 더 낮추지 않은 이유는 그러면 보통 문장의 줄이 필요 이상으로 짧아지기 때문입니다. 아는 한계로 남깁니다.

**측정기가 잘린 값을 실측으로 찍고 있었습니다(고침).** 처음에 "M 42자가 1068px"이라고 적었는데 틀렸습니다. 밝은 화소의 상자는 화면 가장자리에서 멈추므로 넘친 줄은 글자 폭이 아니라 화면 폭이 나옵니다. 그래서 30·34·36·38·40·42자가 **전부 1068px**로 찍혔고, 저는 그걸 측정으로 읽어 영어 한도를 38자로 정했습니다. 근거가 잘린 값이었으니 그 숫자도 근거가 없었습니다. 이제 넘친 줄은 숫자 대신 "넘침"으로 찍고, 판정은 한도를 꽉 채운 줄 하나로 합니다. M 반복은 최악의 글자라 참고로만 찍습니다(라틴은 i와 M이 몇 배 차이라 M 반복을 기준으로 삼으면 실제 문장에 비해 줄이 지나치게 짧아집니다).

**게이트 안내가 이 버전이 안 쓰는 페이지를 짚고 있었습니다(고침).** `default_model_name`이 함수 서명에서 모델 이름을 찾는데, 설치된 whisperx는 거기에 기본값이 없어 None이 나옵니다(CI 로그: `이 버전이 쓰는 모델: None`). 그래서 안내가 옛 페이지(`speaker-diarization-3.1`)만 짚었고, 실제로 막힌 것은 `speaker-diarization-community-1`이었습니다. 동의를 다 해 놓고도 같은 오류를 다시 보게 됩니다. 이제 실패한 이야기에서 저장소 이름을 찾아 그 페이지를 먼저 짚습니다. CI 점검도 실제 저장소 이름을 확인합니다.

**설정(`R4_SUBTITLE_*`)을 바꿨다면 언어가 덮어쓰지 않습니다.** 사람이 정한 값이 우선입니다. 모르는 언어도 받은 값을 그대로 씁니다. 추측해서 바꾸지 않습니다.

영어 한 줄(42자)이 세로 화면 여백 안에 들어가는지는 `measure_subtitles.py`가 CI에서 렌더해 잽니다. 숫자를 바꿨으면 재야 합니다.

### 2. 번역 품질 측정기

`scripts/verify_translate.py`. 사람이 만든 참조 번역과 chrF(문자 n그램 F 점수)로 비교하고, 번역문이 목표 언어 자막 규칙에 들어가는지도 함께 봅니다. 번역이 맞아도 자막으로 안 들어가면 화면에서는 깨집니다.

- **무료 경로**: `--allow-paid` 없이 돌리면 참조 번역만 규칙에 넣어 봅니다. CI가 매번 돕니다(`번역 자막 규칙 확인 (무료)`).
- **유료 경로**: 실제 Google 번역 호출. 자격증명이 있는 컴퓨터에서 사람이 돌립니다. 표본 약 250자 = 0.005 USD 정도. 절차는 [번역 품질 확인](TRANSLATION_CHECK.md).

단어 단위 점수(BLEU) 대신 문자 단위를 쓴 이유: 어순이 자유로운 짧은 문장에서 단어 점수는 심하게 흔들립니다. 하한 0.40은 품질 목표가 아니라 회귀 감시용입니다. 스크립트가 문장별 원문·참조·번역을 항상 찍습니다. 수치 하나로 번역 품질을 말할 수 없습니다.

### 남은 것

- **실제 번역 품질 수치는 아직 없습니다.** 클라우드 세션에 Google 자격증명이 없어 유료 호출을 할 수 없습니다. 사용자가 절차서대로 한 번 돌리면 그때 기록합니다.
- 표본은 네 문장뿐입니다. 긴 대본·구어체·고유명사·존댓말 어조는 알 수 없습니다.
- 더빙 길이 맞춤(번역문이 길어져 음성이 원본 길이에 안 맞는 경우)은 별도 단계이고 여기서 재지 않습니다.
- `LANGUAGE_RULES`에는 한국어와 영어만 있습니다.

## 클립 편집본 자막 파일(SRT·VTT) 내보내기 (2026-09-19)

- 사용자 요청: 깃허브나 다른 사이트에 자막 파일 생성 코드가 있는지 확인하고, 클립 편집본 기준으로 SRT·VTT만 내보내도록 구현. 브랜치 `claude/subtitle-file-generation-38xjz4`.
- 담당 파일: `packages/pipeline/pipeline/subtitle_files.py`(신규), `services/worker/worker/rendering.py`, `services/api/adminapi/routers/editing.py`, `apps/web/src/{api.ts,ClipEditor.tsx}`, `tests/test_subtitle_files.py`(신규), `tests/test_editing_api.py`, `README.md`, `docs/{SHORT_FORM_EDITING,OPEN_SOURCE_INTEGRATIONS,TECH_DECISIONS,HANDOFF}.md`.
- 의존 작업: 없습니다. 새 런타임 의존성도 추가하지 않았습니다(pysubs2는 이미 있습니다).
- **Codex 작업과 겹칠 수 있는 파일**: `routers/editing.py`, `rendering.py`, `ClipEditor.tsx`.

### 조사 결과

자막을 만드는 코드는 이미 있었고 **파일로 내보내는 경로만** 없었습니다. `pipeline/subtitles.py`가 표시 규칙을, `pipeline/alignment.py`가 시각을 만들고, `worker/rendering.py:write_subtitles()`가 pysubs2로 ASS를 씁니다. 그런데 그 ASS는 임시 폴더에 썼다가 FFmpeg로 영상에 구운 뒤 지워집니다. 외부 라이브러리를 더 찾을 필요는 없었습니다. `docs/OPEN_SOURCE_INTEGRATIONS.md`에 이미 `srt`·`webvtt-py`는 pysubs2와 중복이라고 적혀 있습니다.

### 구현한 것

- `pipeline/subtitle_files.py`: `subtitle_file(spec, "srt"|"vtt", rules)`가 편집본 자막을 문자열로 만듭니다. 파일 입출력은 하지 않습니다. ASS 표기 차단(`plain_ass`)을 여기로 옮기고 `rendering.py`가 같은 함수를 씁니다.
- `GET /clips/{id}/subtitles?format=srt|vtt`: 편집본 자막을 파일로 내려줍니다. 기본값은 SRT입니다.
- 관리화면 렌더 결과 줄에 **자막 SRT·VTT 내려받기** 버튼. 자막 파일은 토큰이 필요해 `<a href>`로 바로 받을 수 없어 `api.ts:downloadFile()`이 받아서 저장합니다.

### 설계 판단

- 자막의 출처는 **렌더 요청에 저장된 설정 사본**입니다. 최신 대본을 읽으면 그 뒤에 대본을 고친 경우 영상과 다른 자막을 내보내게 됩니다. 테스트로 고정했습니다.
- 시각은 클립 시작이 0초입니다. 영상에 굽는 경로와 같은 `clip_cues()`·`apply_rules()`를 거치므로 줄바꿈·분할도 화면과 같습니다.
- 화면 제목은 넣지 않습니다. SRT·WebVTT에는 위치 지정이 없어 넣으면 클립 내내 첫 자막과 겹칩니다.
- 저장하지 않고 요청할 때 만듭니다. 저장하면 승인·체크섬 대상 결과물이 하나 더 생기고 편집본과 어긋난 사본이 남을 수 있습니다.
- 자막이 하나도 없는 편집본은 빈 파일을 주지 않고 409로 막습니다. 빈 SRT는 빈 파일이라 실패와 구분되지 않습니다.

### 검증 결과

- `pytest -q`: **287 통과 / 6 skip**(SQLite). 새 테스트 10개(`test_subtitle_files.py` 8, `test_editing_api.py` 2).
- 내보낸 SRT의 시각·줄바꿈이 `write_subtitles()`가 만든 ASS와 자막 단위로 일치함을 테스트로 확인했습니다(제목 이벤트 제외).
- ASS 표기(`{\pos(0,0)}`)를 넣어도 글자가 사라지지 않음을 확인했습니다. 막지 않으면 pysubs2가 SRT로 옮길 때 그 부분을 통째로 지웁니다.
- `ruff check`·`ruff format --check` 통과. `npm run typecheck`·`npm run build` 통과.
- **미검증**: PostgreSQL에서의 실행(CI 대상), 실제 재생기(YouTube·VLC 등)에서의 자막 표시, 브라우저에서의 실제 내려받기 동작.

### 남은 작업

- ~~표시 규칙을 렌더 뒤에 바꾸면 파일 자막이 화면 자막과 달라집니다.~~ 아래 절에서 처리했습니다.
- 외부 SRT를 **가져오는** 경로는 없습니다. 생기면 ffsubsync 도입 시점입니다(`docs/OPEN_SOURCE_INTEGRATIONS.md`).
- 단어별 강조(ASS 전용)와 게시 시 YouTube 자막 트랙 업로드는 이번 범위가 아닙니다.

## 내보낸 자막이 영상과 달라지던 것 (2026-09-19)

- 사용자 요청: "1번부터" — PR #11이 남긴 결함부터 처리. 브랜치 `claude/claude-md-design-review-v8qdz4`.
- 담당 파일: `services/worker/worker/media_tasks.py`, `services/api/adminapi/routers/editing.py`, `tests/test_editing_api.py`, `docs/{TECH_DECISIONS,SHORT_FORM_EDITING,HANDOFF}.md`.
- 의존 작업: 없습니다. 마이그레이션도 없습니다(`MediaTask.result`는 이미 JSON입니다).

### 무엇이 잘못됐나

편집본을 렌더한 뒤 `R4_SUBTITLE_*`를 바꾸면, 내려받은 SRT·VTT가 **그 영상에 구워진 자막과 달랐습니다.** 내보내기가 줄바꿈과 분할을 *지금* 설정으로 다시 계산했기 때문입니다. 문서에 "규칙을 바꾼 편집본은 다시 렌더한다"고 적어 두었지만, 사람은 같은 자막이라고 믿고 그대로 올립니다. 경고문은 고침이 아닙니다.

### 고친 방법

렌더가 그때 쓴 규칙을 `MediaTask.result.subtitle_rules`에 남기고, 내보내기가 그것으로 계산합니다. 새 컬럼도 마이그레이션도 필요 없었습니다.

기록이 없는 옛 편집본은 어쩔 수 없이 지금 설정을 씁니다. **그 사실을 숨기지 않습니다** — 응답 헤더 `X-Subtitle-Rules`가 `rendered`(렌더 때 규칙) 또는 `settings`(옛 기록, 지금 설정)로 나옵니다. 기록이 깨져 있어도 내려받기를 막지 않고 설정으로 내려주면서 `settings`로 알립니다.

### 검증

- `pytest -q`: **307 통과 / 5 skip**(새 테스트 3개).
- 고치기 전 코드로 되돌려 새 테스트가 **실제로 실패하는 것**을 확인했습니다(`x-subtitle-rules`가 `settings`). 통과하는 것만 보면 시험이 헛도는지 알 수 없습니다.
- `ruff check`·`ruff format --check` 통과.

### 남은 작업

- ~~화면 자막이 규칙대로 그려지는지는 아직 못 쟀습니다.~~ 아래 절에서 쟀습니다.
- 외부 SRT를 **가져오는** 경로는 여전히 없습니다.

## 우리가 끊은 줄이 화면에서 그대로 그려지는가 (2026-09-19)

- 사용자 요청: 앞 절에서 남긴 2번. 브랜치 `claude/claude-md-design-review-v8qdz4`.
- 담당 파일: `scripts/measure_subtitles.py`.

### 왜 이것을 쟀나

"넘치면 libass가 제멋대로 다시 줄바꿈해서 우리 줄 규칙이 화면에서 깨집니다." 이 문장이 커밋 메시지와 문서에 몇 번이나 나옵니다. **그런데 그게 실제로 일어나는지는 한 번도 확인한 적이 없었습니다.** 측정기는 한 줄의 폭만 봤습니다.

폭만 재면 이 실패는 **안 보입니다.** 두 줄이 세 줄이 되면 자막이 다른 자리에서 끊기고 화면 위로 더 올라오는데, 줄당 폭은 오히려 줄어듭니다. 통과처럼 보입니다.

### 실측 (2026-09-19 CI, 글자 크기 64)

```
우리가 끊은 줄이 화면에서 그대로 그려지는가
  한글 한 줄: 규칙 1줄 / 화면 1줄  [337x41]
      '다람쥐 헌 쳇바퀴에' (폭 9.0)
  한글 두 줄: 규칙 2줄 / 화면 2줄  [604x41, 116x41]
      '다람쥐 헌 쳇바퀴에 타고파 오늘도' (폭 16.0)
      '즐겁게' (폭 3.0)
  영어 두 줄: 규칙 2줄 / 화면 2줄  [729x48, 632x47]
      'In March last year a colleague of the' (폭 18.5)
      'former minister was appointed' (폭 14.5)
```

**세 경우 모두 우리가 끊은 자리에서 그대로 그려집니다.** 지금 규칙으로는 libass가 다시 줄바꿈하지 않습니다. 이제 CI가 매번 확인합니다.

### 세는 방법과 그 한계

프레임에서 글자가 없는 행으로 끊어 줄을 셉니다. **줄이 더 많이 그려진 경우만 문제로 셉니다.** 적게 나온 것은 외곽선·그림자로 줄 사이가 붙어 보이는 것일 수 있습니다. 세는 방법의 한계를 실패로 보고하면 진짜 실패와 섞입니다. 이번 실측에서는 줄이 붙어 보이는 일이 없었습니다(한글 41px, 영어 47~48px로 각각 따로 잡혔습니다).

대역으로 양쪽 경로를 먼저 확인했습니다. 정상이면 종료 코드 0, libass가 다시 줄바꿈하는 상황을 흉내 내면 "규칙은 2줄인데 화면에는 3줄이 그려졌습니다"로 잡히고 종료 코드 1입니다. 통과만 확인하면 검사가 헛도는지 알 수 없습니다.

### 남은 작업

- ~~세로 위치는 아직 안 봅니다.~~ 아래 절에서 쟀습니다. (여기 "화면 아래로 내려온다"고 적었던 것은 **틀렸습니다.** 자막은 아래에 붙고 줄이 늘면 위로 자랍니다.)
- 실제 재생기(YouTube 등)의 자막 렌더러는 다릅니다. 여기서 재는 것은 우리가 굽는 libass입니다.
## 번역·더빙 작업 자막 파일 내보내기 (2026-09-19)

- 사용자 요청: 자막 파일 생성 관련 코드가 더 없는지 확인하고, 남은 곳 중 1번(작업 경로)부터 구현. 브랜치 `claude/subtitle-file-generation-38xjz4`(PR #11 병합 후 최신 main에서 재시작).
- 담당 파일: `packages/pipeline/pipeline/{subtitle_files,workflow}.py`, `services/api/adminapi/subtitle_rules.py`(신규), `services/api/adminapi/routers/{workflow,editing}.py`, `services/worker/worker/workflow_tasks.py`, `apps/web/src/{api.ts,WorkflowPanel.tsx}`, `tests/{test_subtitle_files,test_connected_workflow}.py`, `README.md`, `docs/{CONNECTED_WORKFLOW,OPEN_SOURCE_INTEGRATIONS,TECH_DECISIONS,HANDOFF}.md`.
- 의존 작업: PR #11(클립 편집본 내보내기)의 `subtitle_files.py`를 확장했습니다. 작업 도중 병합된 PR #10(언어별 자막 규칙)과 PR #12(렌더 규칙 기록)를 main에서 가져와 합쳤습니다(충돌 4건 해결). #12의 `rules_used()`는 공용 `rules_from_record()`를 부르도록 바꿔 두 경로가 같은 판단을 쓰게 했습니다. 새 의존성은 없습니다.
- **Codex 작업과 겹칠 수 있는 파일**: `routers/workflow.py`, `workflow_tasks.py`, `WorkflowPanel.tsx`.

### 조사 결과: 자막을 만드는 곳이 하나 더 있었습니다

`composition.py:render_final()`이 번역·더빙 작업의 자막을 같은 `write_subtitles()`로 만들어 굽고 지웁니다. 클립 경로와 같은 상황이었고, PR #11은 `ClipEdit`만 다뤘습니다. 자막 데이터는 `Job.workflow_data`에 남아 있어 내보내기가 가능했습니다.

### 구현한 것

- `GET /jobs/{id}/subtitles?format=srt|vtt`: 작업 자막을 파일로 내려줍니다. 렌더를 기다리지 않고 대본 단계 뒤부터 받을 수 있습니다.
- `pipeline/workflow.py:rendered_cues()`·`rendered_language()`: 구운 자막을 고르는 순서(`aligned` → `translated` → `cues`)와 그 언어. `workflow_tasks.py`의 렌더 단계가 인라인으로 갖고 있던 식을 이 함수로 바꿨습니다. 두 곳이 어긋날 수 없습니다.
- `subtitle_files.py` 재구성: 핵심은 `subtitle_file(cues, start, end, format, rules)`이고 편집본용은 `clip_subtitle_file(spec, ...)` 래퍼입니다. 작업은 출력 구간이 `0~duration`이라 `EditSpec`(9:16·180초 제한)에 담을 수 없습니다.
- `adminapi/subtitle_rules.py`(신규): 설정 → 표시 규칙. `routers/editing.py`에 있던 함수를 옮겨 두 라우터가 함께 씁니다.
- 관리화면 작업 화면에 **자막 SRT·VTT 내려받기** 버튼. `api.ts:downloadFile()`이 서버가 정한 파일 이름(`job-{id}.{언어}.srt`)을 쓰도록 `Content-Disposition`을 읽습니다.
- 렌더가 쓴 규칙 기록(작업 경로): 렌더 단계가 `Job.workflow_data.subtitle_rules`에 그때 쓴 규칙을 남기고 내보내기가 그것으로 계산합니다. 되살리는 함수는 편집본 경로(#12)와 같은 `adminapi/subtitle_rules.py:rules_from_record()`이며, 응답 헤더 `X-Subtitle-Rules`도 같은 의미(`rendered`/`settings`)로 내려갑니다. 아직 렌더하지 않은 작업은 `settings`입니다.
- 언어별 표시 규칙 연결: main에 먼저 들어간 PR #10이 목표 언어마다 다른 규칙(`rules_for`)을 쓰게 했습니다. 내보내기도 같은 언어 규칙을 쓰도록 `adminapi/subtitle_rules.py:subtitle_rules(language)`를 만들어 연결했습니다. 연결하지 않으면 영어 자막을 한국어 규칙으로 끊어 화면 자막과 줄이 달라집니다.

### 검증 결과

- `pytest -q`: **310 통과 / 6 skip**(SQLite). 새 테스트 7개(#12 병합분 3개 포함 시 10개).
- 원어 작업: 대본 단계 직후 `job-{id}.ko.srt`가 나오고 시각이 원본 대본과 같음을 확인했습니다. 대본 단계 전에는 409입니다.
- 더빙 작업: `aligned`·`translated`·`cues`가 모두 있을 때 **`aligned`만** 나오는 것을 확인했습니다. 렌더가 쓰는 자막과 같습니다.
- 영어 목표 작업의 내보내기가 `rules_for("en")` 결과와 **글자 단위로 같고** 한국어 기본 규칙 결과와는 다름을 확인했습니다. 언어 인자를 빼고 돌려 이 테스트가 실제로 실패하는 것도 확인했습니다.
- 규칙 기록이 있으면 `X-Subtitle-Rules: rendered`로 그 규칙(6자·1줄)에 맞춰 쪼개지고, 없거나 깨졌으면 `settings`로 내려가는 것을 확인했습니다. 기록을 쓰지 않도록 되돌려 이 테스트가 실제로 실패하는 것도 확인했습니다.
- `ruff check`·`ruff format --check` 통과. `npm run typecheck`·`npm run build` 통과.
- **미검증**: PostgreSQL에서의 실행(CI 대상), 실제 재생기에서의 표시, 브라우저에서의 실제 내려받기, 실제 더빙 음성으로 만든 `aligned` 자막의 품질(유료 공급자 필요).

### 남은 작업 (조사에서 확인한 나머지)

- **YouTube 자막 트랙 업로드 없음.** `worker/youtube.py`는 `videos().insert()`만 씁니다. `captions().insert()`가 없어 구운 자막만 나갑니다. 의존성(`google-api-python-client`)과 OAuth 스코프(`youtube.force-ssl`, `connect_youtube.py`)는 이미 있으므로 코드만 추가하면 됩니다. 실제 게시 흐름을 건드리므로 유료·계정 설정 상태를 먼저 확인해야 합니다.
- **외부 SRT 가져오기 없음.** 생기면 ffsubsync 도입 시점입니다.
- ~~우리가 끊은 줄이 화면에서 그대로 그려지는지 미검증.~~ 위 절(#14)이 CI 실측으로 확인했습니다(한글 1·2줄, 영어 2줄 모두 규칙과 화면 줄 수 일치).
- ~~표시 규칙을 렌더 뒤에 바꾸면 파일 자막이 화면 자막과 달라집니다.~~ 위 절(#12)이 편집본 경로를, 이 작업이 작업 경로를 처리했습니다. 두 경로 모두 렌더가 쓴 규칙을 기록에서 되살립니다.

## 자막 세로 위치 (2026-09-19)

- 사용자 요청: 앞 절에서 남긴 "세로 위치는 아직 안 봅니다". 브랜치 `claude/claude-md-design-review-v8qdz4`.
- 담당 파일: `scripts/measure_subtitles.py`.

### 먼저 제가 틀렸던 것

앞 절에 "줄이 늘면 자막이 **화면 아래로** 내려온다"고 적었습니다. **틀렸습니다.** `write_subtitles()`가 쓰는 ASS 기본 정렬은 화면 아래 가운데이고 `marginv`는 **아래 끝에서부터의 거리**입니다. 자막은 아래에 붙어 있고 줄이 늘면 **위로** 자랍니다. 코드를 안 보고 적은 문장이었습니다.

그래서 걱정해야 할 것도 반대입니다. 아래로 밀려 내려가는 게 아니라, 줄이 많아지면 화면 위쪽이나 제목 자리까지 올라옵니다.

### 무엇을 보는가

`marginv`는 `height * 0.13`(1920에서 **249px**), 제목은 위쪽 `height * 0.08`입니다. 측정기가 같은 값을 써서 세 가지를 봅니다.

1. **아래 여백이 지켜지는가.** 자막 아래가 화면 끝에서 249px 떨어져 있어야 합니다. 외곽선 3px과 그림자 1px이 글자 상자 밖으로 나가므로 8px까지는 봐줍니다.
2. **화면 밖으로 잘리지 않는가.** 줄이 늘어도 맨 위 줄이 프레임을 벗어나면 안 됩니다.
3. **제목과 겹치지 않는가.** 겹침은 "구간이 몇 개인가"로 봅니다. 구간은 글자가 없는 행으로 끊으므로 **겹친 두 글덩어리는 한 구간으로 붙습니다.** 제목 없이 그린 자막의 구간 수 + 1이 나와야 떨어져 있는 것입니다.

줄 수는 같은 글(`다람쥐 헌 쳇바퀴에 타고파 오늘도 즐겁게`)에 줄 길이만 바꿔(16·8·6자) 1·2·3·5줄을 만듭니다. 최소 표시 시간을 자막 길이와 같게 두어 시간이 모자라 여러 자막으로 나뉘는 일을 막습니다.

### 검증

측정기는 워커 이미지 안에서만 돌므로 이 세션에서는 못 돌립니다. 렌더를 대역으로 바꿔 **정상 한 가지와 실패 세 가지를 모두** 확인했습니다.

| 경우 | 결과 |
|---|---|
| 정상(줄 41px, 제목 위 8%) | 종료 코드 0 |
| 아래 여백을 안 지킴(249 → 60px) | `자막 아래가 화면에서 60px 떨어져 있습니다` |
| 줄이 너무 커서 프레임을 벗어남 | `자막이 화면 밖으로 잘립니다(위 0, 아래 1670)` |
| 제목이 자막 자리까지 내려옴 | `제목과 자막이 한 덩어리로 그려졌습니다(구간 4개, 떨어져 있으면 6개)` |

**실측값은 CI가 처음 냅니다.**

### 남은 작업

- **재생 화면의 UI 안전 영역은 여전히 모릅니다.** YouTube Shorts는 아래쪽과 오른쪽을 제목·채널·버튼이 덮습니다. 여기서 보는 것은 우리가 설정한 여백이 지켜지는지일 뿐, 그 여백이 플랫폼 UI를 피하기에 충분한지는 **잰 적이 없습니다.** 숫자를 지어내지 않았습니다. 실제 게시 뒤 화면을 보고 정해야 합니다.
- 실제 재생기의 자막 렌더러는 다릅니다. 여기서 재는 것은 우리가 굽는 libass입니다.

## YouTube 자막 트랙 업로드 (2026-09-19)

- 사용자 요청: 자막 조사에서 남은 2번(게시 시 자막 트랙 업로드). 브랜치 `claude/subtitle-file-generation-38xjz4`(PR #13 병합 후 최신 main에서 재시작).
- 담당 파일: `services/api/adminapi/artifact_subtitles.py`(신규), `services/api/adminapi/config.py`, `services/api/adminapi/routers/{editing,workflow}.py`, `services/worker/worker/{youtube,publication_tasks}.py`, `scripts/preflight_publish.py`, `tests/{test_youtube_captions(신규),test_connected_workflow,test_editing_api,test_preflight_publish}.py`, `docs/{PUBLISH_RUNBOOK,CONNECTED_WORKFLOW,OPEN_SOURCE_INTEGRATIONS,TECH_DECISIONS,HANDOFF}.md`.
- 의존 작업: 없습니다. 새 의존성도 없습니다(`google-api-python-client`와 `youtube.force-ssl` 스코프는 이미 있었습니다).

### 구현한 것

- `adminapi/artifact_subtitles.py`(신규): 결과물의 자막을 파일 글자로 만듭니다. 편집본(`MediaTask.settings`)과 작업(`Job.workflow_data`) 양쪽을 다루고, **내려받기 두 엔드포인트와 게시가 모두 이 함수를 씁니다.** 게시용으로 따로 만들면 영상·파일·트랙이 세 갈래로 갈라집니다.
- `worker/youtube.py:upload_captions()`: `captions.insert`. 같은 언어 트랙이 이미 있으면 올리지 않고 `exists`로 돌려줍니다. `sync=False`로 우리 시각을 씁니다.
- `publication_tasks.py:publish_captions()`: 처리 완료 뒤·예약 전에 올립니다. 결과를 `checkpoint.captions`에 남기고, 실패해도 게시를 실패로 만들지 않습니다. 게시 목록 응답에 `captions`로 나옵니다.
- `R4_YOUTUBE_CAPTIONS_ENABLED`(기본 꺼짐)과, 켠 경우에만 `youtube.force-ssl`을 보는 게시 전 점검.

### 검증 결과

- `pytest -q`: **321 통과 / 5 skip**(SQLite, providers 설치 시). 새 테스트 7개.
- 올린 자막 파일이 `GET /jobs/{id}/subtitles` 응답과 **글자 단위로 같음**을 확인했습니다. 같은 함수를 쓰는지 시험으로 고정한 것입니다.
- 같은 언어 트랙이 있으면 `insert`를 부르지 않고, 다시 실행해도 트랙이 늘지 않음을 확인했습니다.
- 자막 업로드가 예외를 던져도 게시 상태는 `scheduled`로 남고 기록에 `failed`가 남는 것을 확인했습니다. 오류 메시지에 자격증명 값이 섞이지 않는 것도 확인했습니다.
- 설정이 꺼져 있으면 `insert`를 부르지 않고 응답의 `captions`가 비어 있음을 확인했습니다.
- `ruff check`·`ruff format --check` 통과.
- **미검증**: **실제 YouTube 계정에 자막 트랙을 올려 본 적은 없습니다.** 대역으로 규약만 확인했습니다. 실제 업로드는 OAuth 연결과 `force-ssl` 권한이 있는 토큰이 필요합니다. 트랙 이름을 빈 값으로 보내는데 실제 API가 어떻게 표시하는지도 확인하지 못했습니다.

### 남은 작업

- **구운 자막과 트랙이 두 벌로 보이는 문제**는 설정을 켜는 사람이 판단해야 합니다. 구운 자막 없이 렌더하는 선택지는 아직 없습니다. 필요하면 편집본·작업에 "자막 굽지 않기" 설정을 넣는 것이 다음 단계입니다.
- 외부 SRT를 **가져오는** 경로는 여전히 없습니다(ffsubsync 자리).
- 관리화면에는 자막 트랙 결과를 아직 보여 주지 않습니다. `GET /publications` 응답에는 들어 있습니다.


## 외부 자막 파일 반입 (2026-09-19)

- 사용자 요청: 자막 조사에서 남은 3번(외부 SRT 가져오기). 브랜치 `claude/subtitle-file-generation-38xjz4`(PR #16 병합 후 최신 main에서 재시작).
- 담당 파일: `packages/pipeline/pipeline/subtitle_files.py`, `services/api/adminapi/routers/editing.py`, `apps/web/src/ClipEditor.tsx`, `tests/{test_subtitle_files,test_editing_api}.py`, `README.md`, `docs/{CONNECTED_WORKFLOW,OPEN_SOURCE_INTEGRATIONS,TECH_DECISIONS,HANDOFF}.md`.
- 의존 작업: 없습니다. 새 의존성도 없습니다(pysubs2가 읽습니다).

### 구현한 것

- `pipeline/subtitle_files.py:parse_subtitles()`: SRT·WebVTT·ASS를 형식 표시 없이 읽습니다. 꾸밈 표기를 벗기고, 파일의 줄바꿈을 공백으로 합치고, 못 쓰는 자막은 **몇 번째를 왜 뺐는지와 함께** 돌려줍니다.
- `POST /source-assets/{id}/transcript/import`: 대본 새 버전으로 저장합니다. 직접 편집과 같은 저장 경로(`save_transcript`)라 원본 길이 검사와 가독성 보고가 똑같이 적용됩니다.
- 편집기에 **자막 파일 가져오기**(파일 선택). 들인 뒤 대본을 다시 읽고 뺀 자막을 알립니다.

### 검증 결과

- `pytest -q`: **330 통과 / 5 skip**(SQLite). 새 테스트 9개.
- 우리가 내보낸 SRT를 다시 들이면 시각·글자가 같음을 확인했습니다(왕복).
- WebVTT 화자 태그(`<v 진행자>`)와 SRT 기울임 표기가 벗겨지는 것, 순서가 뒤섞인 파일이 시간순으로 정렬되는 것을 확인했습니다.
- 자막이 아닌 글자, 쓸 자막이 하나도 없는 파일, 원본 길이를 넘는 자막은 422로 막고 저장하지 않는 것을 확인했습니다.
- `ruff check`·`ruff format --check`, `npm run typecheck`·`npm run build` 통과.
- **미검증**: 실제 외부 도구(Aegisub·유튜브 내려받기 등)가 만든 파일로 시험해 본 적은 없습니다. 인코딩이 UTF-8이 아닌 파일(한국어 SRT에 흔한 CP949)은 **읽지 못합니다.** 브라우저가 `file.text()`로 UTF-8로 읽기 때문입니다.

### 남은 작업

- ~~**인코딩**: CP949·EUC-KR 자막 파일을 어떻게 받을지 정하지 않았습니다.~~ 아래 절에서 처리했습니다.
- **싱크 보정(ffsubsync)**: 반입 경로는 생겼지만 들인 자막이 실제로 얼마나 어긋나는지 재 본 적이 없습니다. 재기 전에 넣으면 맞는 자막을 흔듭니다.
- 자막 두 벌(구운 자막 + YouTube 트랙) 문제는 그대로입니다. 구운 자막 없이 렌더하는 선택지가 필요합니다.


## 자막 파일 인코딩 (2026-09-19)

- 사용자 요청: 앞 절에서 남긴 인코딩 문제. 브랜치 `claude/subtitle-file-generation-38xjz4`(PR #18 병합 후 최신 main에서 재시작).
- 담당 파일: `packages/pipeline/pipeline/subtitle_files.py`, `services/api/adminapi/routers/editing.py`, `apps/web/src/{api.ts,ClipEditor.tsx}`, `tests/{test_subtitle_files,test_editing_api}.py`, `docs/{CONNECTED_WORKFLOW,OPEN_SOURCE_INTEGRATIONS,TECH_DECISIONS,HANDOFF}.md`.
- 의존 작업: PR #18의 반입 경로를 고쳤습니다. 새 의존성은 없습니다.

### 무엇이 문제였나

브라우저가 `file.text()`로 파일을 **UTF-8로 읽어** 보냈습니다. 한국어 자막에 흔한 CP949 파일은 그 자리에서 깨지고, 서버는 깨진 글자만 받습니다. 손쓸 방법이 없습니다.

### 고친 방법

- 파일을 **바이트 그대로**(base64) 보냅니다. 요청 본문이 `text`에서 `content_base64`+`encoding`으로 바뀌었습니다.
- 서버는 BOM과 UTF-8까지만 스스로 판단하고, 그 밖에는 **추측하지 않습니다.** 후보 인코딩마다 첫 자막을 디코딩해 미리보기를 붙여 422로 돌려줍니다.
- 편집기가 그 후보를 버튼으로 보여 주고, 사람이 **글자가 제대로 보이는 것**을 고르면 그 인코딩으로 다시 들입니다.

### 검증 결과

- `pytest -q`: **336 통과 / 5 skip**(SQLite). 새 테스트 6개.
- CP949 파일이 저장되지 않고 후보와 함께 422로 돌아오는 것, 그중 `cp949` 후보의 미리보기가 원래 글자(`안녕하세요 자막입니다`)와 같은 것을 확인했습니다.
- 인코딩을 잘못 지정하면(`utf-8`로 CP949) 저장하지 않고 이유를 돌려주는 것을 확인했습니다.
- 자막으로 읽히지 않는 후보는 내놓지 않는 것(고를 수 없는 선택지), 같은 글자가 나오는 후보를 한 번만 보여 주는 것을 확인했습니다.
- `ruff check`·`ruff format --check`, `npm run typecheck`·`npm run build` 통과.
- **미검증**: 실제 CP949 자막 파일(외부 도구가 만든 것)을 브라우저에서 올려 본 적은 없습니다. 대역 바이트로만 확인했습니다.

### 남은 작업

- ~~싱크 보정(ffsubsync)~~ 아래 절에서 처리했습니다. 보정과 함께 그 보정을 재는 검증도 넣었습니다.
- 자막 두 벌(구운 자막 + YouTube 트랙) 문제도 그대로입니다.


## 자막 싱크 보정 (ffsubsync) (2026-09-19)

- 사용자 요청: ffsubsync 넣기. 앞 절에서 제가 "재기 전에 넣으면 맞는 자막을 흔든다"고 적었으므로 **보정과 그것을 재는 검증을 함께** 넣었습니다. 브랜치 `claude/subtitle-file-generation-38xjz4`.
- 담당 파일: `packages/pipeline/pipeline/subtitle_files.py`, `services/worker/worker/{analysis,media_tasks}.py`, `services/api/adminapi/{models.py,routers/editing.py}`, `migrations/versions/0006_sync_media_task.py`(신규), `apps/web/src/ClipEditor.tsx`, `scripts/verify_sync.py`(신규), `.github/workflows/ci.yml`, `pyproject.toml`, `tests/{test_subtitle_sync(신규),test_editing_api}.py`, `docs/{CONNECTED_WORKFLOW,OPEN_SOURCE_INTEGRATIONS,TECH_DECISIONS,HANDOFF}.md`.
- 의존 작업: `[subtitles]` extra에 `ffsubsync==0.4.27`을 추가했습니다. MIT이며 새 모델 다운로드는 없습니다.

### 구현한 것

- `worker/analysis.py:sync_subtitles()`: ffsubsync 파이썬 API로 시각만 옮깁니다. 글자는 원래 자막에서 가져오고, 자막 개수가 달라지거나 보정기가 실패를 알리면 결과를 쓰지 않습니다.
- `POST /source-assets/{id}/transcript/sync` + `sync` 작업 종류(마이그레이션 `0006_sync`). 결과는 **새 대본 버전**이라 기존 버전이 남습니다.
- 편집기에 **자막 싱크 보정** 버튼. 작업 목록에 "뒤로 2.50초 옮김"처럼 보정값이 나옵니다.
- `pipeline/subtitle_files.py:dump_subtitles()`: 표시 규칙을 거치지 않은 날것 SRT. 규칙을 적용해 보내면 자막이 나뉘어 돌아온 시각을 맞출 수 없습니다.

### 검증 결과

- `pytest -q`: **343 통과 / 5 skip**(SQLite). 새 테스트 7개.
- **실제 ffsubsync로 잽니다.** 기준을 SRT로 주면 오디오·ffmpeg 없이 같은 코드 경로가 돌아, +2.5초와 -2.5초로 밀어 둔 자막이 0.1초 안으로 돌아오는 것을 확인했습니다.
- 보정기가 글자를 다시 써도 우리 글자가 남는 것, 날것 덤프가 자막을 나누지 않는 것을 확인했습니다.
- 마이그레이션 `0006_sync` SQLite 왕복 통과. `ruff check`·`format`, `npm run typecheck` 통과.
- **미검증**: **실제 음성을 기준으로 한 보정은 아직 재지 못했습니다.** `scripts/verify_sync.py`가 CI의 `verify-align` 라벨에서 돌며, 아는 만큼 밀어 둔 자막이 돌아오는지와 **이미 맞는 자막이 흔들리지 않는지**를 함께 봅니다. 이 PR에 라벨을 붙여 실측값을 남기는 것이 다음 차례입니다.

### 남은 작업

- 위 실측(라벨을 붙인 CI 실행). 합성 음성이라 사람 목소리보다 불리한 조건이며, 사람 목소리로도 재려면 `fetch_korean_speech.py` 표본에 같은 검사를 붙이면 됩니다.
- 자막 두 벌(구운 자막 + YouTube 트랙) 문제는 그대로입니다.


## 자막 인코딩 자동 판별 (charset-normalizer) (2026-09-19)

- 사용자 요청: 자동 판별 라이브러리 넣기. 앞 절에서 제가 "추측하지 않는다"고 적었으므로 **판별을 쓰되 무엇으로 읽었는지 밝히고 되돌릴 수 있게** 붙였습니다. 브랜치 `claude/subtitle-file-generation-38xjz4`.
- 담당 파일: `packages/pipeline/pipeline/subtitle_files.py`, `services/api/adminapi/routers/editing.py`, `apps/web/src/{api.ts,ClipEditor.tsx}`, `pyproject.toml`, `tests/{test_subtitle_files,test_editing_api}.py`, `docs/{OPEN_SOURCE_INTEGRATIONS,TECH_DECISIONS,HANDOFF}.md`.
- 의존 작업: **핵심** 의존성에 `charset-normalizer==3.5.1`을 추가했습니다. MIT입니다. chardet은 LGPL이라 쓰지 않았습니다.

### 구현한 것

- `decode_subtitles()`가 **BOM → UTF-8 → 판별기** 순으로 읽고, 글자만이 아니라 `Decoded(text, encoding, detected)`를 돌려줍니다.
- 판별기가 고른 인코딩으로 읽은 글자가 **자막으로 읽히는지** 확인합니다. 읽히지 않으면 쓰지 않고 후보 목록으로 넘어갑니다.
- `encoding_choices()`를 따로 빼서, 판별에 성공했을 때도 같은 후보 목록을 응답에 함께 실어 줍니다.
- 들여오기 응답에 `encoding`·`encoding_detected`·(판별일 때) `choices`가 붙습니다. 편집기는 "cp949로 자동 판별해 읽었습니다. 글자가 제대로 보이는지 확인하세요"를 띄우고 다른 인코딩 버튼을 함께 보여 줍니다. 다시 들이면 대본 새 버전이라 원래 것이 남습니다.

### 검증 결과

- `pytest -q`: **348 통과 / 5 skip**(SQLite).
- CP949로 만든 한국어 자막이 이제 묻지 않고 `cp949`로 들어오며, 응답이 `encoding_detected=true`로 표시하는 것을 확인했습니다. UTF-8은 `false`입니다.
- 판별기가 고르지 못하는 경우(판별 함수를 막고 시험)에는 예전처럼 후보 미리보기와 함께 422로 돌아오고, 저장되지 않는 것을 확인했습니다.
- 판별기가 고른 인코딩으로 **읽히지 않으면** 그 결과를 쓰지 않는 것을 확인했습니다.
- `ruff check`·`ruff format --check`, `npm run typecheck`·`npm run build` 통과.
- **한계(테스트로 남겨 둠)**: 구조 확인은 시간 줄만 봅니다. 글자가 깨져도 자막 파일로는 읽히므로 **판별이 틀린 것을 서버가 걸러내지 못합니다.** `test_decode_marks_a_guess_because_the_check_cannot_catch_garbled_text`가 이 사실을 고정합니다. 그래서 화면에서 사람이 확인하게 했습니다.
- **미검증**: 실제 외부 도구가 만든 CP949·Shift_JIS 파일을 브라우저에서 올려 본 적은 없습니다. 대역 바이트로만 확인했습니다.

### 워커 이미지 빌드 실패와 수정

- ffsubsync를 넣은 커밋에서 **워커 이미지 빌드와 스택 기동 검증이 깨졌습니다**(CI에서 드러났습니다).
- 원인: ffsubsync가 **webrtcvad**(C 확장)를 끌어오는데 PyPI에 파이썬 3.11용 휠이 없어 설치할 때 컴파일해야 합니다. `python:3.11-slim`에는 컴파일러가 없습니다.
- 수정: `infra/Dockerfile.worker`의 설치 층에서만 `build-essential`을 넣었다가 **같은 층에서 지웁니다.** 최종 이미지에는 남지 않습니다.
- ffsubsync는 **chardet(LGPL)** 도 끌어옵니다. 우리 코드는 부르지 않지만 `[subtitles]`를 설치한 워커 이미지에는 들어갑니다. 배포물 라이선스를 따질 때 함께 봐야 합니다(문서에 적어 두었습니다).
- **미검증**: 이 저장소 컨테이너에 도커가 없어 이미지 빌드를 직접 돌려 보지 못했습니다. CI 결과로 확인합니다.

### 남은 작업

- 싱크 보정 실측(`verify-align` 라벨 CI)과 자막 두 벌(구운 자막 + YouTube 트랙) 문제는 그대로입니다.
