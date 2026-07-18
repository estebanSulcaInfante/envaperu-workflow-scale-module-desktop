import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StationPaths:
    root: Path

    def __post_init__(self):
        object.__setattr__(self, "root", Path(self.root).expanduser())

    @classmethod
    def from_environment(cls, environ=None):
        environ = os.environ if environ is None else environ
        explicit_root = environ.get("STATION_DATA_ROOT")
        if explicit_root:
            return cls(Path(explicit_root))

        program_data = environ.get("PROGRAMDATA")
        if program_data:
            base = Path(program_data)
        else:
            # Windows always provides PROGRAMDATA. This fallback keeps local
            # development and non-Windows tests away from the source tree.
            base = Path(environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

        return cls(base / "EnvaPeru" / "Pesaje")

    @property
    def config(self):
        return self.root / "config"

    @property
    def secrets(self):
        return self.root / "secrets"

    @property
    def data(self):
        return self.root / "data"

    @property
    def database(self):
        return self.data / "pesajes.db"

    @property
    def backups(self):
        return self.root / "backups"

    @property
    def logs(self):
        return self.root / "logs"

    @property
    def run(self):
        return self.root / "run"

    @property
    def directories(self):
        return (
            self.config,
            self.secrets,
            self.data,
            self.backups,
            self.logs,
            self.run,
        )

    def ensure_layout(self):
        for directory in self.directories:
            directory.mkdir(parents=True, exist_ok=True)
            if not directory.is_dir():
                raise OSError(f"Station storage path is not a directory: {directory}")
        return self

    def as_config(self):
        return {
            "STATION_DATA_ROOT": str(self.root),
            "STATION_DATABASE_PATH": str(self.database),
            "STATION_BACKUP_DIR": str(self.backups),
            "STATION_LOG_DIR": str(self.logs),
            "STATION_RUN_DIR": str(self.run),
            "STATION_STORAGE_DIRECTORIES": [
                str(directory) for directory in self.directories
            ],
        }


def resolve_station_storage(data_root=None, database_path=None, environ=None):
    environ = os.environ if environ is None else environ
    explicit_database = Path(database_path).expanduser() if database_path else None

    if data_root:
        paths = StationPaths(Path(data_root))
    elif environ.get("STATION_DATA_ROOT"):
        paths = StationPaths.from_environment(environ)
    elif explicit_database is not None:
        # Compatibility mode for the existing BAT and integration tests.
        # New installations should use the ProgramData layout instead.
        paths = StationPaths(explicit_database.parent)
    else:
        paths = StationPaths.from_environment(environ)

    paths.ensure_layout()
    selected_database = explicit_database or paths.database
    selected_database.parent.mkdir(parents=True, exist_ok=True)
    return paths, selected_database
