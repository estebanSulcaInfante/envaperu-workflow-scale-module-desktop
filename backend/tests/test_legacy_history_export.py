import sqlite3
import uuid
from pathlib import Path

from app.services.central_api_client import CentralApiClient
from app.services.legacy_history_export import (
    build_legacy_history_export,
    publish_legacy_history,
)


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        payload = kwargs["json"]
        return FakeResponse(
            {
                "accepted": True,
                "station_id": url.split("/stations/")[1].split("/")[0],
                "import_id": payload["import_id"],
                "chunk_index": payload["chunk_index"],
                "chunks_received": payload["chunk_index"] + 1,
                "total_chunks": payload["total_chunks"],
                "status": (
                    "COMPLETE"
                    if payload["chunk_index"] + 1 == payload["total_chunks"]
                    else "RECEIVING"
                ),
                "received_at_utc": "2026-07-18T18:00:00+00:00",
            }
        )


def _legacy_database(path: Path, row_count=2):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            PRAGMA user_version = 7;
            CREATE TABLE pesajes (
                id INTEGER PRIMARY KEY,
                peso_kg REAL NOT NULL,
                fecha_hora TEXT NOT NULL,
                nro_op TEXT,
                nro_orden_trabajo TEXT,
                molde TEXT,
                color TEXT,
                maquina TEXT,
                turno TEXT,
                operador TEXT,
                deleted_at TEXT,
                observaciones TEXT
            );
            CREATE TABLE ops_cerradas (
                id INTEGER PRIMARY KEY,
                nro_op TEXT NOT NULL,
                molde TEXT,
                motivo TEXT,
                fecha_cierre TEXT NOT NULL
            );
            """
        )
        rows = [
            (
                index,
                25.125 if index == 1 else 10.0,
                f"2026-07-18 0{index}:00:00",
                "OP-0069" if index == 1 else "OP-213",
                "025639",
                "FLORERO AMERICANO",
                "blanco " if index == 1 else "NARAMJA",
                "SOPLADORA-2B",
                "DIA",
                "Operador Uno",
                None if index == 1 else "2026-07-18 10:00:00",
                "dato legacy",
            )
            for index in range(1, row_count + 1)
        ]
        connection.executemany(
            """
            INSERT INTO pesajes (
                id, peso_kg, fecha_hora, nro_op, nro_orden_trabajo, molde,
                color, maquina, turno, operador, deleted_at, observaciones
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.execute(
            """
            INSERT INTO ops_cerradas (
                id, nro_op, molde, motivo, fecha_cierre
            ) VALUES (1, 'OP-0069', 'FLORERO AMERICANO', 'fin de produccion',
                      '2026-07-18 12:00:00')
            """
        )


def test_build_export_is_deterministic_and_preserves_legacy_evidence(tmp_path):
    source = tmp_path / "pesajes-copy.db"
    _legacy_database(source)
    station_id = "7f99acdd-63e6-4385-bc16-b904d5d8d5ee"

    first = build_legacy_history_export(source, station_id, chunk_size=1)
    second = build_legacy_history_export(source, station_id, chunk_size=1)

    assert first == second
    assert uuid.UUID(first.import_id)
    assert first.manifest["source_schema_version"] == 7
    assert first.manifest["source_total_rows"] == 2
    assert first.manifest["source_active_rows"] == 1
    assert first.manifest["source_deleted_rows"] == 1
    assert len(first.chunks) == 2
    assert first.chunks[0]["rows"][0]["color"] == "blanco "
    assert first.chunks[1]["rows"][0]["op"] == "OP-213"
    assert first.chunks[1]["rows"][0]["deleted_at_local"] is not None
    assert first.chunks[0]["rows"][0]["raw"]["observaciones"] == "dato legacy"
    assert first.chunks[0]["closures"][0]["op"] == "OP-0069"
    assert first.chunks[1]["closures"] == []


def test_publish_sends_every_chunk_with_stable_idempotency_key(tmp_path):
    source = tmp_path / "pesajes-copy.db"
    _legacy_database(source)
    station_id = "7f99acdd-63e6-4385-bc16-b904d5d8d5ee"
    export = build_legacy_history_export(source, station_id, chunk_size=1)
    session = FakeSession()
    client = CentralApiClient(
        "https://central.envaperu.test",
        "secret-token",
        "1.1.0-pilot",
        session=session,
    )

    result = publish_legacy_history(client, station_id, export)

    assert result["status"] == "COMPLETE"
    assert len(session.calls) == 2
    for chunk_index, (method, url, kwargs) in enumerate(session.calls):
        assert method == "PUT"
        assert url.endswith(
            f"/legacy-history/imports/{export.import_id}/chunks/{chunk_index}"
        )
        assert kwargs["headers"]["Idempotency-Key"] == (
            f"{export.import_id}:{chunk_index}"
        )

