import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import db
from app.models.pesaje import Pesaje
from app.models.op_cerrada import OpCerrada
from app.services.central_api_client import CentralApiClient, CentralApiError
from app.services.monitoring_service import MonitoringService
from app.services.monitoring_sync_fingerprint import progress_fingerprint, closure_fingerprint
from test_station_monitoring_client import (
    monitoring_app, FakeCentralClient, FakeSession, FakeResponse, _component_provider,
)

NOW = datetime(2026, 7, 17, 15, tzinfo=timezone.utc)


class ReconciledCentral(FakeCentralClient):
    def __init__(self):
        super().__init__()
        self.current_progress = None
        self.current_closures = []
        self.report_receipts = set()
        self.batch_receipts = set()
        self.watermark = 0
        self.import_id = str(uuid.uuid4())
        self.checks = []
        self.command_polls = 0
        self.fail_progress = None

    def get_monitoring_sync_check(self, station_id, payload):
        self.checks.append(copy.deepcopy(payload))
        source = self.current_progress or {**payload, 'rows': []}
        return {'contract_version': 'station-monitoring-sync-v1', 'station_id': station_id,
            'window_start_date': payload['window_start_date'], 'window_end_date': payload['window_end_date'],
            'checked_at_utc': NOW.isoformat(), 'progress_fingerprint': progress_fingerprint(source),
            'closures_fingerprint': closure_fingerprint(self.current_closures) if payload['include_legacy'] else None,
            'legacy_state': {'station_id': station_id, 'initial_import_id': self.import_id,
                'high_watermark': self.watermark, 'contract_version': 'station-legacy-continuity-v1'} if payload['include_legacy'] else None,
            'pending_report_received': payload.get('pending_report_id') in self.report_receipts,
            'pending_batch_received': payload.get('pending_batch_id') in self.batch_receipts}

    def send_production_progress(self, station_id, payload):
        ack = super().send_production_progress(station_id, copy.deepcopy(payload))
        failure = self.fail_progress
        self.fail_progress = None
        if failure == 'before':
            raise CentralApiError('CENTRAL_UNREACHABLE', 'before commit')
        self.current_progress = copy.deepcopy(payload)
        self.report_receipts.add(payload['report_id'])
        if failure == 'after':
            raise CentralApiError('CENTRAL_UNREACHABLE', 'lost ACK')
        return ack

    def send_history_delta(self, station_id, payload):
        ack = super().send_history_delta(station_id, copy.deepcopy(payload))
        self.watermark = max(self.watermark, ack['high_watermark'])
        self.current_closures = copy.deepcopy(payload['closures'])
        self.batch_receipts.add(payload['batch_id'])
        ack['high_watermark'] = self.watermark
        return ack

    def get_pilot_commands(self, station_id):
        self.command_polls += 1
        return super().get_pilot_commands(station_id)

    def acknowledge_pilot_command(self, station_id, command_id, payload):
        ack = super().acknowledge_pilot_command(station_id, command_id, payload)
        self.pilot_commands = []
        return ack


def service(client):
    return MonitoringService(client_factory=lambda _token: client, token_provider=lambda: 'test-token',
                             component_provider=_component_provider, now=lambda: NOW)


def seed():
    row = Pesaje(peso_kg=10, fecha_hora=datetime(2026, 7, 17, 10), nro_op='OP-1')
    db.session.add(row)
    db.session.commit()
    return row


def test_unchanged_snapshots_skip_bodies_but_keep_heartbeat_and_commands(monitoring_app):
    with monitoring_app.app_context():
        seed()
        central = ReconciledCentral()
        monitor = service(central)
        assert monitor.run_once()['state'] == 'ONLINE'
        assert monitor.run_once()['state'] == 'ONLINE'
        assert len(central.checks) == 2
        assert len(central.progress_reports) == len(central.history_deltas) == 1
        assert len(central.heartbeats) == central.command_polls == 2
        assert service(central).run_once()['state'] == 'ONLINE'
        assert len(central.progress_reports) == len(central.history_deltas) == 1


@pytest.mark.parametrize('failure, expected_reports', [('before', 2), ('after', 1)])
def test_failed_send_and_lost_ack_reconcile_without_losing_payload(monitoring_app, failure, expected_reports):
    with monitoring_app.app_context():
        seed()
        central = ReconciledCentral()
        central.fail_progress = failure
        monitor = service(central)
        assert monitor.run_once()['state'] == 'CENTRAL_UNREACHABLE'
        assert monitor.run_once()['state'] == 'ONLINE'
        assert len(central.progress_reports) == expected_reports
        if failure == 'before':
            assert central.progress_reports[0][1]['report_id'] == central.progress_reports[1][1]['report_id']


def test_restore_with_existing_receipt_forces_new_application(monitoring_app):
    with monitoring_app.app_context():
        seed()
        central = ReconciledCentral()
        central.fail_progress = 'after'
        monitor = service(central)
        monitor.run_once()
        first_id = central.progress_reports[-1][1]['report_id']
        central.current_progress = None
        assert monitor.run_once()['state'] == 'ONLINE'
        assert central.progress_reports[-1][1]['report_id'] != first_id
        assert central.current_progress['rows'][0]['weight_kg'] == '10.000'


def test_closure_reopen_and_return_to_previous_snapshot_get_fresh_ids(monitoring_app):
    with monitoring_app.app_context():
        seed()
        central = ReconciledCentral()
        monitor = service(central)
        monitor.run_once()
        closed_at = datetime(2026, 7, 17, 11)
        def close():
            db.session.add(OpCerrada(nro_op='OP-1', molde='MOLD', motivo='audit', fecha_cierre=closed_at))
            db.session.commit()
        close()
        monitor.run_once()
        first_closed_id = central.history_deltas[-1][1]['batch_id']
        OpCerrada.query.delete()
        db.session.commit()
        monitor.run_once()
        assert central.current_closures == []
        close()
        monitor.run_once()
        assert central.current_closures[0]['op'] == 'OP-1'
        assert central.history_deltas[-1][1]['batch_id'] != first_closed_id
        assert len(central.progress_reports) == 1


def test_audited_void_and_backdated_new_capture_change_report(monitoring_app):
    with monitoring_app.app_context():
        row = seed()
        central = ReconciledCentral()
        monitor = service(central)
        monitor.run_once()
        central.pilot_commands = [{'command_id': str(uuid.uuid4()), 'action': 'VOID_CAPTURE', 'legacy_pesaje_id': row.id}]
        monitor.run_once()
        assert central.command_acks[-1][2]['status'] == 'APPLIED'
        assert central.current_progress['rows'] == []
        db.session.add(Pesaje(peso_kg=7, fecha_hora=datetime(2026, 7, 16, 9), nro_op='OP-OLD'))
        db.session.commit()
        monitor.run_once()
        assert central.current_progress['rows'][0]['weight_kg'] == '7.000'
        assert central.current_progress['rows'][0]['operational_date'] == '2026-07-16'
        assert len(central.history_deltas[-1][1]['rows']) == 1


@pytest.mark.parametrize('status', [404, 405])
def test_old_central_falls_back(status, monitoring_app):
    api = CentralApiClient('https://central.example', 'token', 'test',
                           session=FakeSession([FakeResponse(status, {})]))
    central = ReconciledCentral()
    central.get_monitoring_sync_check = api.get_monitoring_sync_check
    with monitoring_app.app_context():
        seed()
        monitor = service(central)
        assert monitor.run_once()['state'] == 'ONLINE'
        assert monitor.run_once()['state'] == 'ONLINE'
        assert len(central.progress_reports) == len(central.history_deltas) == 2
        assert len(api.session.calls) == 1


def test_shared_fingerprint_fixture():
    fixture = json.loads((Path(__file__).resolve().parents[1] / 'contracts' /
                         'station-monitoring-sync-v1/examples.json').read_text())['fingerprint_fixture']
    assert progress_fingerprint(fixture['progress']) == fixture['progress_fingerprint']
    assert closure_fingerprint(fixture['closures']) == fixture['closures_fingerprint']


def test_progress_a_b_a_uses_new_application_identity(monitoring_app):
    with monitoring_app.app_context():
        seed()
        central = ReconciledCentral()
        monitor = service(central)
        monitor.run_once()
        first_id = central.progress_reports[-1][1]['report_id']
        first_hash = progress_fingerprint(central.current_progress)
        second = Pesaje(peso_kg=7, fecha_hora=datetime(2026, 7, 17, 10), nro_op='OP-2')
        db.session.add(second)
        db.session.commit()
        monitor.run_once()
        central.pilot_commands = [{'command_id': str(uuid.uuid4()), 'action': 'VOID_CAPTURE', 'legacy_pesaje_id': second.id}]
        monitor.run_once()
        assert progress_fingerprint(central.current_progress) == first_hash
        assert central.progress_reports[-1][1]['report_id'] != first_id
        assert len(central.progress_reports) == 3
        assert len(monitor._pending_sync) <= 2


@pytest.mark.parametrize('failure', ['before', 'after'])
def test_delta_lost_ack_preserves_identity_or_skips_confirmed_state(monitoring_app, failure):
    with monitoring_app.app_context():
        seed()
        central = ReconciledCentral()
        send_delta = central.send_history_delta
        attempts = []
        def flaky(station_id, payload):
            attempts.append(copy.deepcopy(payload))
            if len(attempts) == 1 and failure == 'before':
                raise CentralApiError('CENTRAL_UNREACHABLE', 'before delta commit')
            result = send_delta(station_id, payload)
            if len(attempts) == 1:
                raise CentralApiError('CENTRAL_UNREACHABLE', 'lost delta ACK')
            return result
        central.send_history_delta = flaky
        monitor = service(central)
        assert monitor.run_once()['state'] == 'CENTRAL_UNREACHABLE'
        assert monitor.run_once()['state'] == 'ONLINE'
        if failure == 'before':
            assert len(attempts) == 2
            assert attempts[0] == attempts[1]
        else:
            assert len(attempts) == 1
        assert len(monitor._pending_sync) == 0


def test_check_error_does_not_suppress_or_fallback_silently(monitoring_app):
    with monitoring_app.app_context():
        seed()
        central = ReconciledCentral()
        def unavailable(*_args):
            raise CentralApiError('CENTRAL_ERROR', 'failed check')
        central.get_monitoring_sync_check = unavailable
        result = service(central).run_once()
        assert result['state'] == 'CENTRAL_ERROR'
        assert central.progress_reports == central.history_deltas == []


def test_window_rollover_and_restore_after_restart_resend(monitoring_app):
    with monitoring_app.app_context():
        seed()
        central = ReconciledCentral()
        monitor = service(central)
        monitor.run_once()
        monitor.now = lambda: datetime(2026, 7, 18, 15, tzinfo=timezone.utc)
        monitor.run_once()
        assert len(central.progress_reports) == 2
        assert central.current_progress['window_end_date'] == '2026-07-18'
        central.current_progress = None
        restarted = service(central)
        restarted.now = monitor.now
        restarted.run_once()
        assert len(central.progress_reports) == 3


def test_idle_cycle_call_and_body_budget(monitoring_app):
    with monitoring_app.app_context():
        seed()
        central = ReconciledCentral()
        monitor = service(central)
        monitor.run_once()
        before = (len(central.heartbeats), len(central.checks), len(central.history_deltas),
                  central.command_polls, len(central.progress_reports))
        monitor.run_once()
        after = (len(central.heartbeats), len(central.checks), len(central.history_deltas),
                 central.command_polls, len(central.progress_reports))
        delta = [end - start for start, end in zip(before, after)]
        assert delta == [1, 1, 0, 1, 0]
        print(json.dumps({'idle_calls_excluding_capabilities': sum(delta),
                          'idle_snapshot_body_bytes': 0,
                          'sync_check_request_bytes': len(json.dumps(central.checks[-1], separators=(',', ':')).encode())}))


def test_unavailable_fingerprint_never_suppresses_full_snapshot(monitoring_app):
    with monitoring_app.app_context():
        seed()
        central = ReconciledCentral()
        check = central.get_monitoring_sync_check
        def oversized(station_id, payload):
            state = check(station_id, payload)
            state['progress_fingerprint'] = None
            state['closures_fingerprint'] = None
            return state
        central.get_monitoring_sync_check = oversized
        monitor = service(central)
        monitor.run_once()
        monitor.run_once()
        assert len(central.progress_reports) == len(central.history_deltas) == 2
