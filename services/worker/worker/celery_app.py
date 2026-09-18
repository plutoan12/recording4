"""Celery 설정.

재전달을 전제로 합니다. 같은 작업을 여러 번 실행해도 문제가 없어야 하므로
중복 방지 키와 입력 해시로 실제 실행 여부를 판단합니다.
"""

from __future__ import annotations

from celery import Celery

from adminapi.config import get_settings

settings = get_settings()

celery_app = Celery("recording4", broker=settings.redis_url, backend=None)
celery_app.conf.update(
    imports=(
        "worker.tasks",
        "worker.link_import",
        "worker.media_tasks",
        "worker.workflow_tasks",
        "worker.publication_tasks",
    ),
    # 늦은 확인. 워커가 죽으면 다른 워커가 다시 받습니다.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # 워커가 미리 쌓아두지 않게 해서 장시간 작업이 한쪽에 몰리지 않게 합니다.
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes={
        # CPU 합성과 업로드는 큐와 동시 실행 수를 분리합니다.
        "worker.workflow_tasks.run_job": {"queue": "render"},
        "worker.publication_tasks.run_publication": {"queue": "upload"},
        "worker.media_tasks.run_media": {"queue": "render"},
        "worker.tasks.render_*": {"queue": "render"},
        "worker.tasks.upload_*": {"queue": "upload"},
    },
    broker_transport_options={
        # 재전달 시간은 최장 단계 실행 시간보다 길게 둡니다. 실제 값은 장애 테스트로 확인합니다.
        "visibility_timeout": 60 * 60 * 6,
    },
    timezone="UTC",
    enable_utc=True,
)
