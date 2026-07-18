import random
import threading


BACKOFF_SECONDS = (5, 15, 30, 60, 120, 300)


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
                    delay = base + self.jitter()
                self.stop_event.wait(delay)

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
