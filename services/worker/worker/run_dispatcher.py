"""outbox 디스패처 실행기.

주기적으로 DB의 미전송 요청을 큐로 보냅니다. 누락·정체 요청은 여기서 다시
집어 올라가므로 큐 전송 실패가 요청 유실로 이어지지 않습니다.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from types import FrameType

from adminapi.db import get_session_factory
from worker.dispatcher import run_once

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = float(os.environ.get("R4_DISPATCH_INTERVAL_SECONDS", "2"))

_running = True


def _stop(_signum: int, _frame: FrameType | None) -> None:
    global _running
    _running = False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    factory = get_session_factory()
    logger.info("디스패처를 시작합니다. 주기 %.1f초", INTERVAL_SECONDS)
    while _running:
        try:
            sent = run_once(factory)
            if sent:
                logger.info("큐로 보낸 요청 %d건", sent)
        except Exception:  # noqa: BLE001 - 한 주기 실패가 루프를 끝내지 않게 합니다.
            logger.exception("디스패치 주기가 실패했습니다.")
        time.sleep(INTERVAL_SECONDS)
    logger.info("디스패처를 종료합니다.")


if __name__ == "__main__":
    main()
