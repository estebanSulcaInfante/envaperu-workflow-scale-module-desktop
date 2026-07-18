import hashlib
import json
import math
import sqlite3
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


CONTRACT_VERSION = "station-legacy-history-v1"
IMPORT_NAMESPACE = uuid.UUID("8617e4ff-f8ac-42e0-b267-84227b1d6f99")


class LegacyHistoryExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class LegacyHistoryExport:
    station_id: str
    import_id: str
    manifest: dict
    chunks: tuple


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_value(value):
    if isinstance(value, bytes):
        return value.hex()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _text(row, *names):
    for name in names:
        if name in row.keys() and row[name] is not None:
            return str(row[name])
    return None


def _weight(value):
    try:
        parsed = Decimal(str(value)).quantize(Decimal("0.001"))
    except (InvalidOperation, TypeError) as exc:
        raise LegacyHistoryExportError(f"peso legacy invalido: {value!r}") from exc
    if parsed <= 0:
        raise LegacyHistoryExportError(f"peso legacy debe ser positivo: {value!r}")
    return format(parsed, "f")


def _table_names(connection):
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _read_rows(connection):
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(pesajes)").fetchall()
    }
    required = {"id", "peso_kg", "fecha_hora"}
    missing = required - columns
    if missing:
        raise LegacyHistoryExportError(
            "pesajes.db no contiene columnas requeridas: " + ", ".join(sorted(missing))
        )

    exported = []
    for row in connection.execute("SELECT * FROM pesajes ORDER BY id"):
        deleted_at = _text(row, "deleted_at")
        exported.append(
            {
                "legacy_id": int(row["id"]),
                "weight_kg": _weight(row["peso_kg"]),
                "captured_at_local": _text(row, "fecha_hora"),
                "deleted_at_local": deleted_at,
                "op": _text(row, "nro_op", "op"),
                "ot": _text(row, "nro_orden_trabajo", "ot"),
                "mold": _text(row, "molde"),
                "color": _text(row, "color"),
                "machine_code": _text(row, "maquina", "machine_code"),
                "shift": _text(row, "turno", "shift"),
                "operator": _text(row, "operador", "maquinista", "operator"),
                "raw": {key: _json_value(row[key]) for key in row.keys()},
            }
        )
    return exported


def _read_closures(connection, tables):
    if "ops_cerradas" not in tables:
        return []
    return [
        {
            "op": _text(row, "nro_op", "op"),
            "mold": _text(row, "molde"),
            "reason": _text(row, "motivo", "reason"),
            "closed_at_local": _text(row, "fecha_cierre", "closed_at"),
        }
        for row in connection.execute("SELECT * FROM ops_cerradas ORDER BY id")
    ]


def build_legacy_history_export(source_path, station_id, *, chunk_size=500):
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise LegacyHistoryExportError(f"copia SQLite no encontrada: {source}")
    try:
        canonical_station_id = str(uuid.UUID(str(station_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LegacyHistoryExportError("station_id debe ser UUID") from exc
    if not 1 <= int(chunk_size) <= 500:
        raise LegacyHistoryExportError("chunk_size debe estar entre 1 y 500")

    source_hash = _file_sha256(source)
    source_size = source.stat().st_size
    try:
        with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            tables = _table_names(connection)
            if "pesajes" not in tables:
                raise LegacyHistoryExportError("la copia SQLite no contiene pesajes")
            schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
            rows = _read_rows(connection)
            closures = _read_closures(connection, tables)
    except sqlite3.DatabaseError as exc:
        raise LegacyHistoryExportError(f"SQLite legacy no se pudo leer: {exc}") from exc

    if source_hash != _file_sha256(source) or source_size != source.stat().st_size:
        raise LegacyHistoryExportError(
            "la fuente cambio durante la lectura; use una copia estatica cerrada"
        )

    captures = [row["captured_at_local"] for row in rows if row["captured_at_local"]]
    deleted_rows = sum(row["deleted_at_local"] is not None for row in rows)
    manifest = {
        "source_sha256": source_hash,
        "source_size_bytes": source_size,
        "source_schema_version": int(schema_version),
        "source_total_rows": len(rows),
        "source_active_rows": len(rows) - deleted_rows,
        "source_deleted_rows": deleted_rows,
        "source_first_capture_local": min(captures) if captures else None,
        "source_last_capture_local": max(captures) if captures else None,
    }
    import_id = str(
        uuid.uuid5(IMPORT_NAMESPACE, f"{canonical_station_id}:{source_hash}")
    )
    total_chunks = max(
        1,
        math.ceil(len(rows) / chunk_size),
        math.ceil(len(closures) / 500),
    )
    chunks = []
    for chunk_index in range(total_chunks):
        chunks.append(
            {
                "contract_version": CONTRACT_VERSION,
                "import_id": import_id,
                "manifest": manifest,
                "chunk_index": chunk_index,
                "total_chunks": total_chunks,
                "rows": rows[
                    chunk_index * chunk_size : (chunk_index + 1) * chunk_size
                ],
                "closures": closures[chunk_index * 500 : (chunk_index + 1) * 500],
            }
        )
    return LegacyHistoryExport(
        station_id=canonical_station_id,
        import_id=import_id,
        manifest=manifest,
        chunks=tuple(chunks),
    )


def publish_legacy_history(client, station_id, export):
    canonical_station_id = str(uuid.UUID(str(station_id)))
    if export.station_id != canonical_station_id:
        raise LegacyHistoryExportError("el export pertenece a otra estacion")
    last_ack = None
    for chunk in export.chunks:
        last_ack = client.send_legacy_history_chunk(
            canonical_station_id,
            export.import_id,
            chunk["chunk_index"],
            chunk,
        )
    return last_ack


def export_summary(export):
    return json.dumps(
        {
            "station_id": export.station_id,
            "import_id": export.import_id,
            "manifest": export.manifest,
            "total_chunks": len(export.chunks),
        },
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )

