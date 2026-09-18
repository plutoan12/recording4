# 개발 환경

이 문서는 구현된 범위를 실행하는 방법만 다룹니다. 설계는 [시스템 설계](ARCHITECTURE.md), 진행 상황은 [인수인계](HANDOFF.md)를 봅니다.

## 현재 구현된 범위

[구현 계획](IMPLEMENTATION_PLAN.md)의 2단계(기본 기반)입니다. 로그인, 원본 등록과 검증, 작업 생성·목록·상태 전이, outbox를 통한 큐 전달, 원본 파일 검사 워커가 동작합니다. STT·번역·더빙·합성·YouTube 게시는 아직 없습니다. 외부 유료 API는 호출하지 않습니다.

## 필요한 것

- Python 3.11 이상
- Node.js 22 이상
- Docker와 Docker Compose (PostgreSQL, Redis, S3 호환 저장소용)
- FFmpeg (워커 컨테이너에는 포함되어 있습니다. 로컬에서 워커를 직접 실행할 때만 필요합니다)

## Docker Compose로 실행

```bash
cp .env.example .env    # 값을 확인하고 비밀을 바꿉니다
docker compose -f infra/docker-compose.yml up --build
```

API는 http://localhost:8000, API 문서는 http://localhost:8000/docs, MinIO 콘솔은 http://localhost:9001 입니다. API 컨테이너가 시작할 때 마이그레이션을 적용합니다.

관리화면은 따로 띄웁니다.

```bash
cd apps/web
npm install
npm run dev     # http://localhost:5173
```

## 관리자 계정 만들기

관리자 가입 화면은 없습니다. 첫 계정은 다음처럼 만듭니다.

```bash
docker compose -f infra/docker-compose.yml exec api python - <<'PY'
from adminapi.db import get_session_factory
from adminapi.models import User
from adminapi.security import hash_password

with get_session_factory()() as session:
    session.add(User(email="admin@example.com", password_hash=hash_password("비밀번호-12자이상")))
    session.commit()
PY
```

비밀번호는 12자 이상이어야 합니다. 실제 비밀번호를 저장소에 커밋하지 않습니다.

## 로컬에서 직접 실행

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export PYTHONPATH=packages/pipeline:services/api:services/worker

alembic upgrade head
uvicorn adminapi.main:app --reload                      # 관리 API
celery -A worker.celery_app.celery_app worker -l info   # 워커
python -m worker.run_dispatcher                         # outbox 디스패처
```

## 검사

```bash
ruff check . && ruff format --check .
pytest -q
```

테스트는 기본적으로 임시 SQLite에서 돌아갑니다. 동시 예약 경합 테스트는 행 잠금이 필요해 PostgreSQL에서만 실행됩니다. 로컬에서 함께 돌리려면 다음처럼 합니다.

```bash
R4_DATABASE_URL=postgresql+psycopg://recording4:devpass@localhost:5432/recording4 pytest -q
```

CI는 PostgreSQL 서비스에서 전체 테스트를 실행합니다.

## 저장소 구조

```text
apps/web/               React 관리화면
services/api/adminapi/  FastAPI 관리 API
services/worker/worker/ Celery 워커, ffprobe 검사, outbox 디스패처
packages/pipeline/      상태 전이표, 입력 해시, 예산 규칙 (공유 도메인)
migrations/             Alembic 마이그레이션
tests/                  상태 전이·해시·예산·API·워커 테스트
infra/                  Dockerfile과 Compose 구성
```

## 주의

- 비밀키, OAuth 토큰, 실제 영상, 개인정보가 담긴 로그를 커밋하지 않습니다.
- `.env`는 커밋하지 않습니다. `.env.example`만 저장소에 둡니다.
- 서명 URL은 API만 발급하고 로그에 남기지 않습니다.

## 추가된 영상 기능

[오픈소스 통합·실행 안내](OPEN_SOURCE_INTEGRATIONS.md)에 로컬 CLI, 선택 의존성, 미디어 작업 API, 실행 및 검증 한계를 정리했습니다. 기존 DB는 `alembic upgrade head`가 필요합니다. Docker 워커 이미지를 다시 빌드하면 FFmpeg·한국어 글꼴·분석 라이브러리가 설치됩니다.
