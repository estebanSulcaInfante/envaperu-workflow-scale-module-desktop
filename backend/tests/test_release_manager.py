import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from station_release import (
    ActiveReleaseStore,
    ReleasePackageError,
    build_manifest,
    stage_release,
    verify_release_directory,
)


def _write_release(root: Path, version: str, content: str = "release") -> Path:
    (root / "backend").mkdir(parents=True)
    (root / "frontend" / "dist").mkdir(parents=True)
    (root / "backend" / "station_main.py").write_text(content, encoding="utf-8")
    (root / "frontend" / "dist" / "index.html").write_text(
        f"<h1>{content}</h1>", encoding="utf-8"
    )
    build_manifest(root, app_version=version, source_revision="test-revision")
    return root


def _archive_release(release_root: Path, archive_path: Path) -> str:
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(path for path in release_root.rglob("*") if path.is_file()):
            archive.write(file_path, file_path.relative_to(release_root).as_posix())
    return hashlib.sha256(archive_path.read_bytes()).hexdigest()


def test_manifest_verifies_every_declared_release_file(tmp_path):
    release_root = _write_release(tmp_path / "release", "1.2.0")

    manifest = verify_release_directory(release_root)

    assert manifest["app_version"] == "1.2.0"
    assert {entry["path"] for entry in manifest["files"]} == {
        "backend/station_main.py",
        "frontend/dist/index.html",
    }


def test_manifest_rejects_a_file_changed_after_build(tmp_path):
    release_root = _write_release(tmp_path / "release", "1.2.0")
    (release_root / "backend" / "station_main.py").write_text(
        "tampered", encoding="utf-8"
    )

    with pytest.raises(ReleasePackageError, match="mismatch"):
        verify_release_directory(release_root)


def test_runtime_venv_and_python_cache_do_not_invalidate_an_installed_release(tmp_path):
    release_root = _write_release(tmp_path / "release", "1.2.0")
    (release_root / "backend" / "venv" / "Scripts").mkdir(parents=True)
    (release_root / "backend" / "venv" / "Scripts" / "python.exe").write_bytes(b"runtime")
    cache = release_root / "backend" / "app" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "config.cpython-312.pyc").write_bytes(b"cache")

    assert verify_release_directory(release_root)["app_version"] == "1.2.0"


def test_stage_requires_the_expected_package_checksum(tmp_path):
    release_root = _write_release(tmp_path / "release", "1.2.0")
    archive_path = tmp_path / "envaperu-pesaje-1.2.0-win-x64.zip"
    checksum = _archive_release(release_root, archive_path)

    with pytest.raises(ReleasePackageError, match="SHA-256"):
        stage_release(
            archive_path,
            install_root=tmp_path / "install",
            expected_sha256="0" * 64,
        )

    result = stage_release(
        archive_path,
        install_root=tmp_path / "install",
        expected_sha256=checksum,
    )
    assert result.version == "1.2.0"
    assert result.release_path.name == "1.2.0"
    assert verify_release_directory(result.release_path)["app_version"] == "1.2.0"


def test_zip_path_traversal_is_rejected_without_writing_outside_install_root(tmp_path):
    archive_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "forbidden")
        archive.writestr("manifest.json", json.dumps({"schema_version": 1}))
    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()

    with pytest.raises(ReleasePackageError, match="unsafe"):
        stage_release(
            archive_path,
            install_root=tmp_path / "install",
            expected_sha256=checksum,
        )

    assert not (tmp_path / "outside.txt").exists()


def test_activation_and_rollback_only_switch_the_pointer(tmp_path):
    install_root = tmp_path / "install"
    data_root = tmp_path / "program-data"
    store = ActiveReleaseStore(install_root=install_root, data_root=data_root)

    first = install_root / "releases" / "1.1.0"
    second = install_root / "releases" / "1.2.0"
    _write_release(first, "1.1.0", "first")
    _write_release(second, "1.2.0", "second")

    first_state = store.activate("1.1.0")
    second_state = store.activate("1.2.0", preupdate_backup="backup-1.1.0.db")
    rolled_back = store.rollback()

    assert first_state["active_version"] == "1.1.0"
    assert second_state["active_version"] == "1.2.0"
    assert second_state["previous_version"] == "1.1.0"
    assert rolled_back["active_version"] == "1.1.0"
    assert rolled_back["previous_version"] == "1.2.0"
    assert first.is_dir() and second.is_dir()
    assert json.loads(store.state_path.read_text(encoding="utf-8")) == rolled_back


def test_failed_staging_does_not_change_active_release(tmp_path):
    install_root = tmp_path / "install"
    data_root = tmp_path / "program-data"
    active = install_root / "releases" / "1.1.0"
    _write_release(active, "1.1.0", "stable")
    store = ActiveReleaseStore(install_root=install_root, data_root=data_root)
    before = store.activate("1.1.0")

    broken_root = _write_release(tmp_path / "broken", "1.2.0", "broken")
    (broken_root / "backend" / "station_main.py").write_text(
        "changed-after-manifest", encoding="utf-8"
    )
    archive_path = tmp_path / "broken.zip"
    checksum = _archive_release(broken_root, archive_path)

    with pytest.raises(ReleasePackageError, match="mismatch"):
        stage_release(
            archive_path,
            install_root=install_root,
            expected_sha256=checksum,
        )

    assert store.read() == before
    assert not (install_root / "releases" / "1.2.0").exists()
