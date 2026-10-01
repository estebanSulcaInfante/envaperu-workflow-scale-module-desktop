from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.runtime import monitoring_worker as worker_module


class StopAfterWaits:
    def __init__(self, count=1):
        self.count = count
        self.delays = []

    def is_set(self):
        return len(self.delays) >= self.count

    def wait(self, delay):
        self.delays.append(delay)
        return self.is_set()


def make_worker(results):
    results = iter(results)
    service = SimpleNamespace(run_once=lambda: next(results))
    app = SimpleNamespace(app_context=nullcontext, config={})
    return worker_module.MonitoringWorker(app, service_factory=lambda: service, jitter=lambda: 0.5)


@pytest.mark.parametrize('retry_after, expected', [('120', 120), ('1', 5.5), ('bad', 5.5), ('-1', 5.5)])
def test_worker_respects_server_delay_without_shortening_backoff(retry_after, expected):
    worker = make_worker([{'state': 'RATE_LIMITED', 'retry_after': retry_after}])
    worker.stop_event = StopAfterWaits()
    worker._run()
    assert worker.stop_event.delays == [expected]


def test_backoff_and_online_reset_remain_unchanged():
    worker = make_worker([
        {'state': 'CENTRAL_ERROR'}, {'state': 'CENTRAL_ERROR'},
        {'state': 'ONLINE', 'next_heartbeat_seconds': 30},
        {'state': 'CENTRAL_ERROR'},
    ])
    worker.stop_event = StopAfterWaits(4)
    worker._run()
    assert worker.stop_event.delays == [5.5, 15.5, 30, 5.5]


@pytest.mark.parametrize('value, expected', [
    ('Thu, 01 Oct 2026 15:02:00 GMT', 120),
    ('Thu, 01 Oct 2026 14:00:00 GMT', 0),
    ('0', 0), (' 120 ', 120), ('1.5', 0), ('NaN', 0),
    ('Infinity', 0), (None, 0), ('9' * 129, 0),
])
def test_retry_after_parsing(value, expected):
    now = datetime(2026, 10, 1, 15, tzinfo=timezone.utc)
    assert worker_module._retry_after_seconds(value, now=now) == expected


def test_large_server_delay_remains_interruptible_without_overflow():
    worker = make_worker([{'state': 'RATE_LIMITED', 'retry_after': '9' * 100}])
    worker.stop_event = StopAfterWaits(2)
    worker._run()
    assert worker.stop_event.delays == [3600, 3600]
