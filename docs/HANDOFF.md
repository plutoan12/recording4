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
| 2026-09-18 | Claude | 2단계 기본 기반 구현. 브랜치 `claude/claude-md-design-review-v8qdz4`. 담당 파일은 아래 후속 기록 참조 | API·워커·관리화면·마이그레이션·CI 추가. 테스트 117개 통과. 다음은 실제 S3·FFmpeg 연동 확인과 3단계 |

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

- `pytest -q`: 117개 통과, 1개 건너뜀(동시 예약 경합 테스트는 PostgreSQL 전용이며 이 환경에서는 Docker 데몬이 없어 실행하지 못했습니다. CI에서 PostgreSQL 서비스로 실행합니다).
- `ruff check .`, `ruff format --check .`: 통과.
- `alembic upgrade head` → `downgrade base` → `upgrade head`: SQLite에서 통과. PostgreSQL 적용은 CI에서 확인합니다.
- 프런트엔드 `tsc -b --noEmit`, `vite build`: 통과.
- 수행하지 못한 검증: 실제 S3·MinIO 연동, 실제 FFmpeg 실행, Docker Compose 기동, 브라우저 화면 확인. 이 환경에는 Docker 데몬과 ffprobe가 없습니다. 저장소와 ffprobe는 테스트에서 대역으로 바꿨습니다.

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
