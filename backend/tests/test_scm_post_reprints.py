from copy import deepcopy
import hashlib
import json
from uuid import uuid4

import pytest
from flask import Flask

from app import db
from app.services.printer_service import PrinterEmissionResult
from app.services.scm_post_reprint_service import PostReprintRenderer, PostReprintService
from app.models.scm_post_reprint import ScmPostReprintJournal


def job(copies=1):
    result = {'copy_job_id': str(uuid4()), 'job_kind': 'POSTPESAJE_COPY',
            'renderer_version': PostReprintRenderer.VERSION, 'copias': copies,
            'source_label_id': str(uuid4()), 'source_pesaje_id': str(uuid4()),
            'payload_hash': 'a'*64,
            'payload': {'document_type': 'POSTPESAJE', 'codigo_manga': 'OF80-OT71-M002',
                        'template': {'version': 'POSTPESAJE_TSPL_5'},
                        'peso_neto_real_kg': '8.950', 'kg_fisico': '8.950',
                        'cantidad_confirmada_un': '100', 'maquinista': 'MUESTRA',
                        'pieza_color': 'MUESTRA'}}
    result['payload_hash'] = hashlib.sha256(json.dumps(result['payload'], ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return result


def versioned_identity(mode="CATALOG_SNAPSHOT", variant="TOLVA MUESTRA ROJO SOLIDO PREMIUM"):
    return {
        "version": 1,
        "mode": mode,
        "captured_at": "2026-10-07T16:00:00Z",
        "pieza": {"id": "pieza-1", "codigo": "PZ-001", "nombre": "TOLVA MUESTRA", "version": 2},
        "color": {"id": "color-1", "nombre": "ROJO SOLIDO", "source": "MANGA_SNAPSHOT"},
        "variante": {
            "sku": "VAR-001",
            "nombre": variant,
            "catalog_version": "catalog-1" if mode == "CATALOG_SNAPSHOT" else None,
            "catalog_version_source": "SCM_ARTICULO",
            "source": "MANGA_SNAPSHOT",
        },
        "provenance": {"fixture": "test"},
    }


class Client:
    def __init__(self, item):
        self.item = item
        self.claims = 0
        self.acks = []
        self.offline = False

    def claim_post_reprint_job(self, station, id, attempt):
        self.claims += 1
        if self.offline:
            raise RuntimeError('offline')
        return {**deepcopy(self.item), 'station_id': station, 'attempt_id': attempt}

    def ack_post_reprint_job(self, station, id, evidence):
        if self.offline:
            raise RuntimeError('offline')
        self.acks.append(deepcopy(evidence))
        return {'copy_job_id': id, 'attempt_id': evidence['attempt_id'], 'result': evidence['result']}


class Printer:
    printer_name = 'FAKE_ONLY'

    def __init__(self, status='ACCEPTED', after=None):
        self.calls = []
        self.status = status
        self.after = after

    def print_tspl_result(self, tspl):
        self.calls.append(tspl)
        if self.after:
            self.after()
        return PrinterEmissionResult(self.status, len(tspl.encode()),
                                     bytes_written=len(tspl.encode()), simulated=True)


@pytest.fixture
def app(tmp_path):
    application = Flask(__name__)
    application.config.update(SQLALCHEMY_DATABASE_URI=f'sqlite:///{tmp_path}/journal.db',
                              STATION_UUID='station-test', SCM_POST_REPRINT_ENABLED=True)
    db.init_app(application)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()


@pytest.mark.parametrize('copies', [1, 2, 3, 7])
def test_exact_copy_count_no_inherited_double(copies):
    tspl, svg = PostReprintRenderer().render(job(copies))
    assert tspl.count('OF80-OT71-M002') == copies
    assert tspl.count('PRINT 1,1') == (copies+1)//2
    assert svg.count('OF80-OT71-M002') == copies
    assert 'QRCODE' not in tspl


def test_copy_renderer_uses_catalog_snapshot_identity_and_keeps_tspl_svg_in_sync():
    item = job(copies=3)
    item["payload"]["identidad_producto"] = versioned_identity("CATALOG_SNAPSHOT")
    item["payload_hash"] = hashlib.sha256(json.dumps(
        item["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()

    tspl, svg = PostReprintRenderer().render(item)

    assert tspl.count("PZ: TOLVA MUESTRA") == 3
    assert tspl.count("COLOR: ROJO SOLIDO") == 3
    assert tspl.count("VAR: TOLVA MUESTRA ROJO SOLIDO") == 3
    assert svg.count("PZ: TOLVA MUESTRA") == 3
    assert svg.count("COLOR: ROJO SOLIDO") == 3
    assert svg.count("VAR: TOLVA MUESTRA ROJO SOLIDO") == 3
    assert "SIN QR" not in tspl
    assert "SIN QR" not in svg


def test_copy_renderer_keeps_legacy_manga_snapshot_on_legacy_layout():
    item = job(copies=1)
    item["payload"]["identidad_producto"] = versioned_identity("LEGACY_MANGA_SNAPSHOT")
    item["payload"]["identidad_producto"]["pieza"] = None
    item["payload_hash"] = hashlib.sha256(json.dumps(
        item["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()

    tspl, svg = PostReprintRenderer().render(item)

    assert "NO USAR" not in tspl
    assert "PZ:" not in tspl and "COLOR:" not in tspl and "VAR:" not in tspl
    assert "MUESTRA" in tspl and "MUESTRA" in svg


def test_pre_and_unknown_renderer_blocked():
    item = job()
    item['payload']['document_type'] = 'PREPESAJE'
    with pytest.raises(ValueError):
        PostReprintRenderer().render(item)
    item = job()
    item['renderer_version'] = 'unknown'
    with pytest.raises(ValueError):
        PostReprintRenderer().render(item)


def test_replay_and_lost_ack_never_reprints(app):
    item = job()
    client = Client(item)
    printer = Printer(after=lambda: setattr(client, 'offline', True))
    service = PostReprintService(client=client, printer=printer)
    first = service.execute(item['copy_job_id'])
    assert first['ack_pending']
    assert first['result'] == 'ACCEPTED'
    db.session.remove()
    client.offline = False
    recovered = service.execute(item['copy_job_id'])
    assert not recovered['ack_pending']
    assert len(printer.calls) == 1
    assert len(client.acks) == 1
    assert client.claims == 1


def test_reservation_durable_before_first_byte(app):
    item = job()
    def assert_reserved():
        with db.engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT state FROM scm_post_reprint_journal').scalar() == 'EMITTING'
    printer = Printer(after=assert_reserved)
    PostReprintService(client=Client(item), printer=printer).execute(item['copy_job_id'])


def test_uncertain_and_orphan_reservation_block(app):
    item = job()
    client = Client(item)
    printer = Printer('UNCERTAIN')
    service = PostReprintService(client=client, printer=printer)
    assert service.execute(item['copy_job_id'])['result'] == 'UNCERTAIN'
    assert service.execute(item['copy_job_id'])['result'] == 'UNCERTAIN'
    assert len(printer.calls) == 1
    orphan = ScmPostReprintJournal(copy_job_id=str(uuid4()), attempt_id=str(uuid4()),
                                  station_id='station-test', state='RESERVED')
    db.session.add(orphan)
    db.session.commit()
    result = service.execute(orphan.copy_job_id)
    assert result['result'] == 'UNCERTAIN'
    assert len(printer.calls) == 1


def test_offline_claim_never_prints(app):
    item = job()
    client = Client(item)
    client.offline = True
    printer = Printer()
    result = PostReprintService(client=client, printer=printer).execute(item['copy_job_id'])
    assert result['result'] == 'UNCERTAIN'
    assert not printer.calls


def test_feature_disabled(app):
    app.config['SCM_POST_REPRINT_ENABLED'] = False
    with pytest.raises(ValueError, match='habilitada'):
        PostReprintService(client=Client(job()), printer=Printer()).execute(str(uuid4()))


def test_tampered_source_never_reaches_printer(app):
    item = job()
    item['payload']['peso_neto_real_kg'] = '100'
    printer = Printer()
    result = PostReprintService(client=Client(item), printer=printer).execute(item['copy_job_id'])
    assert result['result'] == 'NOT_EMITTED'
    assert not printer.calls


def test_malformed_identity_never_reaches_printer_or_ack(app):
    item = job()
    item['payload']['identidad_producto'] = {'version': 2}
    item['payload_hash'] = hashlib.sha256(json.dumps(
        item['payload'], ensure_ascii=False, sort_keys=True, separators=(',', ':')
    ).encode()).hexdigest()
    client = Client(item)
    printer = Printer()

    result = PostReprintService(client=client, printer=printer).execute(item['copy_job_id'])

    assert result['result'] == 'NOT_EMITTED'
    assert result['evidence']['expected_bytes'] == 0
    assert result['evidence']['write_attempted'] is False
    assert not printer.calls
    assert not client.acks


def test_control_characters_cannot_inject_tspl():
    item = job()
    item['payload']['maquinista'] = 'MUESTRA\nPRINT 999,999'
    item['payload_hash'] = hashlib.sha256(json.dumps(item['payload'], ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    with pytest.raises(ValueError, match='controles'):
        PostReprintRenderer().render(item)


def test_versioned_variant_control_characters_never_reach_renderer():
    item = job()
    item['payload']['identidad_producto'] = versioned_identity(
        variant='TOLVA MUESTRA ROJO\nCONFITECA'
    )
    item['payload_hash'] = hashlib.sha256(json.dumps(
        item['payload'], ensure_ascii=False, sort_keys=True, separators=(',', ':')
    ).encode()).hexdigest()
    with pytest.raises(ValueError, match='controles'):
        PostReprintRenderer().render(item)


def test_process_loss_after_emission_boundary_never_replays(app):
    item = job()
    def crash():
        raise SystemExit('simulated process loss')
    printer = Printer(after=crash)
    service = PostReprintService(client=Client(item), printer=printer)
    with pytest.raises(SystemExit):
        service.execute(item['copy_job_id'])
    db.session.remove()
    printer.after = None
    result = service.execute(item['copy_job_id'])
    assert result['result'] == 'UNCERTAIN'
    assert result['state'] == 'EMITTING'
    assert len(printer.calls) == 1


def test_concurrent_execute_reserves_one_copy_job(app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    item, printer = job(), Printer()
    client = Client(item)
    barrier = Barrier(2)
    def execute():
        with app.app_context():
            barrier.wait(timeout=5)
            return PostReprintService(client=client, printer=printer).execute(item['copy_job_id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.submit(execute), pool.submit(execute)
        assert {one.result()['result'], two.result()['result']} <= {'ACCEPTED', 'UNCERTAIN'}
    assert len(printer.calls) == 1
    assert client.claims == 1


@pytest.mark.parametrize('field', ['attempt_id', 'station_id', 'copy_job_id'])
def test_crossed_claim_does_not_print(app, field):
    item, printer = job(), Printer()
    class CrossedClient(Client):
        def claim_post_reprint_job(self, station, id, attempt):
            response = super().claim_post_reprint_job(station, id, attempt)
            response[field] = str(uuid4())
            return response
    client = CrossedClient(item)
    result = PostReprintService(client=client, printer=printer).execute(item['copy_job_id'])
    assert result['result'] == 'NOT_EMITTED'
    assert result['state'] == 'CLAIM_RESPONSE_REJECTED'
    assert not result['ack_pending']
    assert not client.acks
    assert not printer.calls


def test_unrelated_200_ack_remains_pending(app):
    item, printer = job(), Printer()
    class InvalidReceiptClient(Client):
        def ack_post_reprint_job(self, *args):
            return {'ok': True}
    result = PostReprintService(client=InvalidReceiptClient(item), printer=printer).execute(item['copy_job_id'])
    assert result['ack_pending']
    assert len(printer.calls) == 1


@pytest.mark.parametrize('status', [401, 403, 404, 409, 422])
def test_definitive_claim_rejection_is_terminal_without_pending_ack(app, status):
    from app.services.central_api_client import CentralApiError
    item, printer = job(), Printer()
    class RejectedClient(Client):
        def claim_post_reprint_job(self, *args):
            raise CentralApiError('REJECTED', 'rejected', http_status=status)
    client = RejectedClient(item)
    result = PostReprintService(client=client, printer=printer).execute(item['copy_job_id'])
    assert result['result'] == 'NOT_EMITTED'
    assert result['state'] == 'CLAIM_REJECTED'
    assert not result['ack_pending']
    assert not printer.calls
    assert not client.acks
