#!/usr/bin/env bash
# 로컬 검사. CI의 "파이썬 검사" 잡과 같은 3.11 컨테이너 안에서 돌립니다.
#
#   scripts/dev_check.sh            # 전체 검사
#   scripts/dev_check.sh pytest -q tests/test_alignment.py   # 한 명령만
#
# 이미지가 없으면 먼저 만듭니다. 코드는 마운트하므로 고칠 때마다 다시 빌드하지
# 않아도 됩니다. pyproject.toml을 고쳤을 때만 --rebuild로 다시 만듭니다.
set -uo pipefail

IMAGE="recording4-dev:local"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ "${1:-}" = "--rebuild" ]; then
    shift
    docker image rm -f "$IMAGE" >/dev/null 2>&1 || true
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "검사용 이미지를 만듭니다 (처음 한 번, 몇 분 걸립니다)"
    docker build -q -f infra/Dockerfile.dev -t "$IMAGE" . || exit 1
fi

# 컨테이너 안에서 명령 하나를 돌립니다. 저장소를 통째로 마운트합니다.
# DB는 기본값(SQLite)이라 PostgreSQL 전용 테스트는 건너뜁니다. 그 테스트까지
# 보려면 R4_DATABASE_URL로 PostgreSQL 주소를 넘깁니다.
run() {
    docker run --rm \
        -v "$ROOT:/app" -w /app \
        -e R4_JWT_SECRET=dev-secret-value \
        -e "R4_DATABASE_URL=${R4_DATABASE_URL:-}" \
        "$IMAGE" "$@"
}

# 명령을 직접 넘기면 그것만 돌리고 끝냅니다.
if [ "$#" -gt 0 ]; then
    run "$@"
    exit $?
fi

# 첫 실패에서 멈추지 않고 전부 돌린 뒤 모아서 보고합니다. 린트 하나 때문에
# 테스트 결과를 못 보면 고치는 왕복이 늘어납니다. CI는 반대로 멈춥니다.
FAILED=()

step() {
    local name="$1"
    shift
    printf '\n=== %s ===\n' "$name"
    if run "$@"; then
        return 0
    fi
    FAILED+=("$name")
    return 1
}

step "린트" ruff check .
step "포맷" ruff format --check .
# 마이그레이션 DB는 컨테이너 임시 경로에 만듭니다. 저장소에 파일을 남기지 않습니다.
step "마이그레이션 왕복" bash -c '
    export R4_DATABASE_URL=sqlite+pysqlite:////tmp/dev-check.db
    rm -f /tmp/dev-check.db
    alembic upgrade head && alembic downgrade base && alembic upgrade head
' >/dev/null
step "테스트" pytest -q

printf '\n=== 결과 ===\n'
if [ "${#FAILED[@]}" -eq 0 ]; then
    echo "모두 통과"
    exit 0
fi
printf '실패: %s\n' "${FAILED[*]}"
exit 1
