import sqlite3
from uuid import uuid4

from app.runtime.token_store import StationTokenStore
from app.storage.paths import StationPaths
from station_control import _initialize_identity, _pilot_config_report


def _configured_station(tmp_path):
    paths = StationPaths(tmp_path / "station")
    paths.ensure_layout()
    station_id = str(uuid4())
    with sqlite3.connect(paths.database) as connection:
        connection.execute(
            "CREATE TABLE station_identity "
            "(station_id TEXT PRIMARY KEY, station_code TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO station_identity (station_id, station_code) VALUES (?, ?)",
            (station_id, "PESAJE-PILOT-01"),
        )
    (paths.secrets / "station-token.dpapi").write_bytes(b"encrypted-token")
    return paths, station_id


def test_initialize_identity_is_idempotent_and_rejects_a_different_provision(
    tmp_path,
):
    paths = StationPaths(tmp_path / "station")
    paths.ensure_layout()
    with sqlite3.connect(paths.database) as connection:
        connection.execute(
            "CREATE TABLE station_identity ("
            "station_id TEXT PRIMARY KEY, station_code TEXT NOT NULL UNIQUE, "
            "created_at_utc TEXT NOT NULL, provisioned_at_utc TEXT)"
        )
    station_id = str(uuid4())

    assert _initialize_identity(paths.root, station_id, "PESAJE-PILOT-01") == 0
    assert _initialize_identity(paths.root, station_id, "PESAJE-PILOT-01") == 0
    assert _initialize_identity(paths.root, str(uuid4()), "PESAJE-PILOT-01") == 7

    with sqlite3.connect(paths.database) as connection:
        rows = connection.execute(
            "SELECT station_id, station_code, created_at_utc, provisioned_at_utc "
            "FROM station_identity"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0:2] == (station_id, "PESAJE-PILOT-01")
    assert rows[0][2]
    assert rows[0][3]


def test_pilot_preflight_accepts_complete_central_configuration(
    tmp_path, monkeypatch,
):
    paths, station_id = _configured_station(tmp_path)
    monkeypatch.setattr(StationTokenStore, "read", lambda _self: "token")

    report = _pilot_config_report(
        paths.root,
        environ={
            "SCM_OPERATOR_ID": "27",
            "CENTRAL_ORIGIN": "https://central.envaperu.test",
            "ALLOW_INSECURE_CENTRAL": "false",
            "STATION_UUID": station_id,
            "STATION_CODE": "PESAJE-PILOT-01",
            "STATION_MODE": "MONITORED_LEGACY",
        },
    )

    assert report["valid"] is True
    assert report["status"] == "PILOT_CONFIG_READY"
    assert report["issues"] == []
    assert report["scm_operator_id"] == 27
    assert report["station_id"] == station_id
    assert report["configured_station_id"] == station_id
    assert report["station_code"] == "PESAJE-PILOT-01"
    assert report["simulation_flags"] == []
    assert report["token_storage"] == "DPAPI"


def test_pilot_preflight_rejects_missing_operator_and_central(tmp_path):
    paths = StationPaths(tmp_path / "station")
    paths.ensure_layout()

    report = _pilot_config_report(paths.root, environ={})

    assert report["valid"] is False
    assert report["status"] == "PILOT_CONFIG_INVALID"
    assert {issue["code"] for issue in report["issues"]} >= {
        "SCM_OPERATOR_ID_INVALID",
        "CENTRAL_ORIGIN_REQUIRED",
        "STATION_UUID_REQUIRED",
        "STATION_IDENTITY_NOT_INITIALIZED",
        "STATION_TOKEN_REQUIRED",
    }


def test_pilot_preflight_rejects_identity_mismatch_and_simulation(
    tmp_path, monkeypatch,
):
    paths, station_id = _configured_station(tmp_path)
    monkeypatch.setattr(StationTokenStore, "read", lambda _self: "token")

    report = _pilot_config_report(
        paths.root,
        environ={
            "SCM_OPERATOR_ID": "27",
            "CENTRAL_ORIGIN": "https://central.envaperu.test",
            "ALLOW_INSECURE_CENTRAL": "false",
            "STATION_UUID": str(uuid4()),
            "STATION_CODE": "PESAJE-OTRA-01",
            "STATION_MODE": "MONITORED_LEGACY",
            "ALLOW_SCALE_SIMULATION": "true",
            "SIMULATE_PRINTER": "true",
        },
    )

    assert report["valid"] is False
    assert report["station_id"] == station_id
    assert set(report["simulation_flags"]) == {
        "ALLOW_SCALE_SIMULATION",
        "SIMULATE_PRINTER",
    }
    assert {issue["code"] for issue in report["issues"]} >= {
        "STATION_IDENTITY_MISMATCH",
        "STATION_CODE_MISMATCH",
        "PHYSICAL_PILOT_SIMULATION_ENABLED",
    }
