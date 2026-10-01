import random
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


BACKOFF_SECONDS = (5, 15, 30, 60, 120, 300)


def _retry_after_seconds(value, *, now=None):
    if not isinstance(value, str):
        return 0
    value = value.strip()
    # Bound untrusted header parsing; retain long valid waits as integers.
    if not value or len(value) > 128:
        return 0
    if value.isascii() and value.isdecimal():
        return int(value)
    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0, (retry_at - (now or datetime.now(timezone.utc))).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return 0


class MonitoringWorker:
    def __init__(self, app, service_factory=None, jitter=None):
        self.app = app
        self.service_factory = service_factory
        self.jitter = jitter or (lambda: random.uniform(0, 1))
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="CentralHeartbeatWorker",
        )
        self.thread.start()

    def _run(self):
        from app.services.monitoring_service import MonitoringService

        with self.app.app_context():
            service = (
                self.service_factory()
                if self.service_factory is not None
                else MonitoringService()
            )
            failure_index = 0
            while not self.stop_event.is_set():
                result = service.run_once()
                state = result["state"]
                if state == "ONLINE":
                    failure_index = 0
                    delay = max(5, int(result["next_heartbeat_seconds"]))
                elif state == "CENTRAL_NOT_PROVISIONED":
                    failure_index = 0
                    delay = max(
                        30,
                        int(self.app.config.get("HEARTBEAT_SECONDS", 30)),
                    )
                else:
                    base = BACKOFF_SECONDS[min(failure_index, len(BACKOFF_SECONDS) - 1)]
                    failure_index += 1
                    delay = max(
                        base + self.jitter(),
                        _retry_after_seconds(result.get("retry_after")),
                    )
                self._wait(delay)

    def _wait(self, delay):
        # Chunk long HTTP delays to avoid platform timeout overflow without
        # retrying early. Every chunk can still be interrupted by stop().
        while delay > 0:
            chunk = min(delay, 3600)
            if self.stop_event.wait(chunk):
                return
            delay -= chunk

    def stop(self, timeout=5):
        self.stop_event.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=timeout)
        stopped = self.thread is None or not self.thread.is_alive()
        if stopped:
            self.thread = None
        return stopped


_monitoring_worker = None


def start_monitoring_worker(app):
    global _monitoring_worker
    if _monitoring_worker is None:
        _monitoring_worker = MonitoringWorker(app)
    _monitoring_worker.start()
    return _monitoring_worker


def stop_monitoring_worker(timeout=5):
    global _monitoring_worker
    if _monitoring_worker is None:
        return True
    stopped = _monitoring_worker.stop(timeout=timeout)
    if stopped:
        _monitoring_worker = None
    return stopped
