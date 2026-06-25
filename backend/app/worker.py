# File: backend/app/worker.py
"""
Execution worker — drains the durable queue out-of-request.

Run alongside the API as a separate process:  `python -m app.worker`

It is intentionally thin: a loop that claims and runs one job at a time via
`ExecutionQueueService.run_once`, sleeping briefly when the queue is empty. State,
idempotency, and bounded retry all live in the queue service, so this stays a
trivial driver — and scaling to multiple workers is just running it more than once
(the atomic claim guarantees each job runs once). The API process never depends on
the worker for inline paths; the worker is the durable executor for queued work.
"""

from __future__ import annotations

import logging
import signal
import time

from app.core.config import settings
from app.execution_queue import execution_queue
from app.job_handlers import register_default_handlers

logger = logging.getLogger("aira_x.worker")


class ExecutionWorker:
    def __init__(self, poll_seconds: float | None = None) -> None:
        self.poll_seconds = poll_seconds if poll_seconds is not None else settings.worker_poll_seconds
        self._stop = False
        register_default_handlers()

    def stop(self, *_: object) -> None:
        self._stop = True

    def run_forever(self) -> None:
        logger.info("AIRA-X execution worker started (poll=%.1fs)", self.poll_seconds)
        while not self._stop:
            try:
                ran = execution_queue.run_once()
            except Exception:  # a worker must never die on one bad job
                logger.exception("worker run_once failed")
                ran = None
            if ran is None:
                # Idle: flush any pending external webhook deliveries (bounded,
                # best-effort — a failed delivery never affects execution).
                try:
                    from app.webhooks import delivery_service

                    delivery_service.deliver_pending()
                except Exception:
                    logger.exception("worker deliver_pending failed")
                time.sleep(self.poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    worker = ExecutionWorker()
    signal.signal(signal.SIGINT, worker.stop)
    signal.signal(signal.SIGTERM, worker.stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
