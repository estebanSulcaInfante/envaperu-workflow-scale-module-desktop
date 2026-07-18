from pathlib import Path

from sqlalchemy import event


def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=FULL")
    finally:
        cursor.close()


def configure_sqlite_engine(engine):
    if engine.dialect.name != "sqlite":
        return engine
    if not event.contains(engine, "connect", _set_sqlite_pragmas):
        event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


def database_path_from_engine(engine):
    if engine.dialect.name != "sqlite":
        return None
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    return Path(database).expanduser().resolve()
