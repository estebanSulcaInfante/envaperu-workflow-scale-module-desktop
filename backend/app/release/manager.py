from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 1
RELEASE_STATE_SCHEMA_VERSION = 1
MUTABLE_RELEASE_PREFIXES = ("backend/venv/",)
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class ReleasePackageError(ValueError):
    """Raised when a release cannot be trusted or activated safely."""


@dataclass(frozen=True)
class StagedRelease:
    version: str
    release_path: Path
    package_sha256: str
    reused_existing: bool


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_version(version: str):
    if not isinstance(version, str) or not SEMVER_PATTERN.fullmatch(version):
        raise ReleasePackageError(
            f"Release app_version must be semantic versioning, found {version!r}"
        )
    return version


def _relative_release_files(root: Path):
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == MANIFEST_NAME:
            continue
        if (
            any(relative.startswith(prefix) for prefix in MUTABLE_RELEASE_PREFIXES)
            or "__pycache__" in PurePosixPath(relative).parts
            or relative.endswith((".pyc", ".pyo"))
        ):
            continue
        yield path, relative


def build_manifest(
    root,
    *,
    app_version,
    source_revision,
    minimum_python="3.12",
    platform="win-x64",
):
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ReleasePackageError(f"Release root does not exist: {root}")
    version = _validate_version(app_version)
    files = [
        {
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path, relative in _relative_release_files(root)
    ]
    if not files:
        raise ReleasePackageError("Release must contain at least one declared file")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "app_version": version,
        "source_revision": str(source_revision or "unknown"),
        "created_at_utc": _utc_now(),
        "runtime": {
            "minimum_python": str(minimum_python),
            "platform": str(platform),
        },
        "files": files,
    }
    manifest_path = root / MANIFEST_NAME
    temporary = root / f".{MANIFEST_NAME}.{uuid.uuid4().hex}.tmp"
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, manifest_path)
    return manifest


def _load_manifest(root: Path):
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ReleasePackageError("Release manifest.json is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleasePackageError(f"Release manifest is invalid: {exc}") from exc
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ReleasePackageError(
            "Unsupported release manifest schema_version: "
            f"{manifest.get('schema_version')!r}"
        )
    _validate_version(manifest.get("app_version"))
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("platform") != "win-x64":
        raise ReleasePackageError("Release runtime.platform must be win-x64")
    if not isinstance(manifest.get("files"), list) or not manifest["files"]:
        raise ReleasePackageError("Release manifest files must be a non-empty list")
    return manifest


def _safe_declared_path(root: Path, raw_path):
    if not isinstance(raw_path, str) or not raw_path:
        raise ReleasePackageError("Release manifest contains an empty file path")
    candidate = PurePosixPath(raw_path)
    if candidate.is_absolute() or ".." in candidate.parts or ":" in raw_path:
        raise ReleasePackageError(f"Release manifest contains unsafe path: {raw_path}")
    resolved = (root / Path(*candidate.parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReleasePackageError(
            f"Release manifest contains unsafe path: {raw_path}"
        ) from exc
    return resolved, candidate.as_posix()


def verify_release_directory(root):
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ReleasePackageError(f"Release directory does not exist: {root}")
    manifest = _load_manifest(root)
    declared = set()
    for entry in manifest["files"]:
        if not isinstance(entry, dict):
            raise ReleasePackageError("Release manifest file entry must be an object")
        path, relative = _safe_declared_path(root, entry.get("path"))
        if relative in declared:
            raise ReleasePackageError(f"Release manifest repeats path: {relative}")
        declared.add(relative)
        if not path.is_file():
            raise ReleasePackageError(f"Declared release file is missing: {relative}")
        expected_size = entry.get("size_bytes")
        if not isinstance(expected_size, int) or expected_size < 0:
            raise ReleasePackageError(f"Invalid size for release file: {relative}")
        if path.stat().st_size != expected_size:
            raise ReleasePackageError(f"Release file size mismatch: {relative}")
        expected_hash = str(entry.get("sha256", "")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise ReleasePackageError(f"Invalid checksum for release file: {relative}")
        if _sha256(path) != expected_hash:
            raise ReleasePackageError(f"Release file checksum mismatch: {relative}")

    actual = {relative for _, relative in _relative_release_files(root)}
    undeclared = sorted(actual - declared)
    missing = sorted(declared - actual)
    if undeclared:
        raise ReleasePackageError(
            "Release contains undeclared files: " + ", ".join(undeclared[:5])
        )
    if missing:
        raise ReleasePackageError(
            "Release is missing declared files: " + ", ".join(missing[:5])
        )
    return manifest


def _validate_archive_member(info: zipfile.ZipInfo):
    raw_name = info.filename.replace("\\", "/")
    candidate = PurePosixPath(raw_name)
    if (
        not raw_name
        or candidate.is_absolute()
        or ".." in candidate.parts
        or ":" in raw_name
    ):
        raise ReleasePackageError(f"Release archive contains unsafe path: {raw_name}")
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    if unix_mode and stat.S_ISLNK(unix_mode):
        raise ReleasePackageError(f"Release archive contains unsafe symlink: {raw_name}")
    return candidate


def _extract_verified_archive(archive_path: Path, destination: Path):
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                relative = _validate_archive_member(info)
                target = (destination / Path(*relative.parts)).resolve()
                try:
                    target.relative_to(destination)
                except ValueError as exc:
                    raise ReleasePackageError(
                        f"Release archive contains unsafe path: {info.filename}"
                    ) from exc
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise ReleasePackageError(f"Release archive is not a valid ZIP: {exc}") from exc


def stage_release(package_path, *, install_root, expected_sha256):
    package_path = Path(package_path).expanduser().resolve()
    install_root = Path(install_root).expanduser().resolve()
    if not package_path.is_file():
        raise ReleasePackageError(f"Release package does not exist: {package_path}")
    expected = str(expected_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ReleasePackageError("Expected package SHA-256 must contain 64 hex digits")
    actual = _sha256(package_path)
    if actual != expected:
        raise ReleasePackageError(
            f"Release package SHA-256 mismatch: expected {expected}, found {actual}"
        )

    releases_root = install_root / "releases"
    releases_root.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".staging-", dir=str(releases_root))
    ).resolve()
    try:
        _extract_verified_archive(package_path, staging)
        manifest = verify_release_directory(staging)
        version = manifest["app_version"]
        target = (releases_root / version).resolve()
        target.relative_to(releases_root.resolve())
        if target.exists():
            existing = verify_release_directory(target)
            if existing != manifest:
                raise ReleasePackageError(
                    f"Release {version} already exists with different contents"
                )
            return StagedRelease(version, target, actual, True)
        os.replace(staging, target)
        staging = None
        return StagedRelease(version, target, actual, False)
    finally:
        if staging is not None and staging.exists():
            staging.relative_to(releases_root.resolve())
            shutil.rmtree(staging)


class ActiveReleaseStore:
    def __init__(self, *, install_root, data_root):
        self.install_root = Path(install_root).expanduser().resolve()
        self.data_root = Path(data_root).expanduser().resolve()
        self.releases_root = self.install_root / "releases"
        self.state_path = self.data_root / "run" / "active-release.json"

    def read(self):
        if not self.state_path.is_file():
            return None
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleasePackageError(f"Active release state is invalid: {exc}") from exc
        if state.get("schema_version") != RELEASE_STATE_SCHEMA_VERSION:
            raise ReleasePackageError("Active release state schema is unsupported")
        self._release_path(state.get("active_version"))
        previous = state.get("previous_version")
        if previous is not None:
            self._release_path(previous)
        return state

    def _release_path(self, version):
        version = _validate_version(version)
        path = (self.releases_root / version).resolve()
        try:
            path.relative_to(self.releases_root.resolve())
        except ValueError as exc:
            raise ReleasePackageError(f"Release path escapes install root: {version}") from exc
        if not path.is_dir():
            raise ReleasePackageError(f"Installed release does not exist: {version}")
        verify_release_directory(path)
        return path

    def _write(self, state):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.parent / (
            f".{self.state_path.name}.{uuid.uuid4().hex}.tmp"
        )
        temporary.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, self.state_path)
        return state

    def activate(
        self,
        version,
        *,
        preupdate_backup=None,
        validation_baseline=None,
    ):
        release_path = self._release_path(version)
        current = self.read()
        if current and current.get("active_version") == version:
            raise ReleasePackageError(
                f"Release {version} is already active; activate a new immutable version"
            )
        state = {
            "schema_version": RELEASE_STATE_SCHEMA_VERSION,
            "active_version": version,
            "active_path": str(release_path),
            "previous_version": current.get("active_version") if current else None,
            "previous_path": current.get("active_path") if current else None,
            "activated_at_utc": _utc_now(),
            "preupdate_backup": str(preupdate_backup) if preupdate_backup else None,
            "validation_baseline": (
                str(validation_baseline) if validation_baseline else None
            ),
        }
        return self._write(state)

    def rollback(self):
        current = self.read()
        if not current or not current.get("previous_version"):
            raise ReleasePackageError("No previous release is available for rollback")
        previous_version = current["previous_version"]
        previous_path = self._release_path(previous_version)
        state = {
            "schema_version": RELEASE_STATE_SCHEMA_VERSION,
            "active_version": previous_version,
            "active_path": str(previous_path),
            "previous_version": current["active_version"],
            "previous_path": current["active_path"],
            "activated_at_utc": _utc_now(),
            "preupdate_backup": current.get("preupdate_backup"),
            "validation_baseline": current.get("validation_baseline"),
        }
        return self._write(state)
