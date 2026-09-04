import argparse
import importlib.util
import json
import sys
from pathlib import Path


_MANAGER_PATH = Path(__file__).resolve().parent / "app" / "release" / "manager.py"
_MANAGER_SPEC = importlib.util.spec_from_file_location(
    "envaperu_station_release_manager", _MANAGER_PATH
)
if _MANAGER_SPEC is None or _MANAGER_SPEC.loader is None:
    raise RuntimeError(f"Cannot load release manager from {_MANAGER_PATH}")
_MANAGER = importlib.util.module_from_spec(_MANAGER_SPEC)
sys.modules[_MANAGER_SPEC.name] = _MANAGER
_MANAGER_SPEC.loader.exec_module(_MANAGER)

ActiveReleaseStore = _MANAGER.ActiveReleaseStore
ReleasePackageError = _MANAGER.ReleasePackageError
build_manifest = _MANAGER.build_manifest
stage_release = _MANAGER.stage_release
verify_release_directory = _MANAGER.verify_release_directory


def _parser():
    parser = argparse.ArgumentParser(description="Manage versioned station releases")
    commands = parser.add_subparsers(dest="command", required=True)

    manifest = commands.add_parser("manifest")
    manifest.add_argument("--root", type=Path, required=True)
    manifest.add_argument("--version", required=True)
    manifest.add_argument("--source-revision", default="unknown")

    verify = commands.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)

    stage = commands.add_parser("stage")
    stage.add_argument("--package", type=Path, required=True)
    stage.add_argument("--install-root", type=Path, required=True)
    stage.add_argument("--expected-sha256", required=True)

    activate = commands.add_parser("activate")
    activate.add_argument("--version", required=True)
    activate.add_argument("--install-root", type=Path, required=True)
    activate.add_argument("--data-root", type=Path, required=True)
    activate.add_argument("--preupdate-backup")

    current = commands.add_parser("current")
    current.add_argument("--install-root", type=Path, required=True)
    current.add_argument("--data-root", type=Path, required=True)

    rollback = commands.add_parser("rollback")
    rollback.add_argument("--install-root", type=Path, required=True)
    rollback.add_argument("--data-root", type=Path, required=True)
    return parser


def _print(event, **payload):
    print(json.dumps({"event": event, **payload}, sort_keys=True), flush=True)


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == "manifest":
            manifest = build_manifest(
                args.root,
                app_version=args.version,
                source_revision=args.source_revision,
            )
            _print("RELEASE_MANIFEST_CREATED", manifest=manifest)
            return 0
        if args.command == "verify":
            manifest = verify_release_directory(args.root)
            _print("RELEASE_VERIFIED", manifest=manifest)
            return 0
        if args.command == "stage":
            result = stage_release(
                args.package,
                install_root=args.install_root,
                expected_sha256=args.expected_sha256,
            )
            _print(
                "RELEASE_STAGED",
                version=result.version,
                release_path=str(result.release_path),
                package_sha256=result.package_sha256,
                reused_existing=result.reused_existing,
            )
            return 0

        store = ActiveReleaseStore(
            install_root=args.install_root,
            data_root=args.data_root,
        )
        if args.command == "activate":
            state = store.activate(
                args.version,
                preupdate_backup=args.preupdate_backup,
            )
            _print("RELEASE_ACTIVATED", state=state)
            return 0
        if args.command == "rollback":
            state = store.rollback()
            _print("RELEASE_ROLLED_BACK", state=state)
            return 0
        _print("ACTIVE_RELEASE", state=store.read())
        return 0
    except (ReleasePackageError, OSError) as exc:
        _print(
            "RELEASE_ERROR",
            error_type=type(exc).__name__,
            detail=str(exc),
        )
        return 8


if __name__ == "__main__":
    raise SystemExit(main())
