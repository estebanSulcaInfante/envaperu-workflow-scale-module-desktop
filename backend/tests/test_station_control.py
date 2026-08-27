import sqlite3
from uuid import uuid4

from app.runtime.token_store import StationTokenStore
from app.storage.paths import StationPaths
from station_control import _pilot_config_report


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
        },
    )

    assert report["valid"] is True
    assert report["status"] == "PILOT_CONFIG_READY"
    assert report["issues"] == []
    assert report["scm_operator_id"] == 27
    assert report["station_id"] == station_id
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
        "STATION_IDENTITY_NOT_INITIALIZED",
        "STATION_TOKEN_REQUIRED",
    }
