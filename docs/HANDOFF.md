# 협업 인수인계

최종 갱신: 2026-09-18

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

- 자막 화면: 글자 크기 64에서 한글 16자는 **647px**(화면 폭의 60%), 여백 980px 안에 한 줄. 20자까지 들어갑니다. 한 줄 높이 41px.
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

- 합성 음성(espeak) 기준입니다. 사람 목소리에서의 정확도는 여전히 미검증입니다.
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
