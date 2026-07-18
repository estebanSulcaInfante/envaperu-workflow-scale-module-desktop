import hashlib
import os
import re
import tempfile
from pathlib import Path


INSTANCE_ALREADY_RUNNING_EXIT_CODE = 73
ERROR_ALREADY_EXISTS = 183


class InstanceAlreadyRunning(RuntimeError):
    pass


def _safe_station_id(station_id):
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", station_id.strip())
    if not value:
        raise ValueError("station_id must contain at least one valid character")
    return value


class StationMutex:
    def __init__(self, station_id):
        safe_station_id = _safe_station_id(station_id)
        self.name = f"Local\\EnvaPeruPesaje-{safe_station_id}"
        self._handle = None
        self._lock_file = None

    def acquire(self):
        if os.name == "nt":
            self._acquire_windows()
        else:
            self._acquire_posix()
        return self

    def _acquire_windows(self):
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())

        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            raise InstanceAlreadyRunning(self.name)

        self._handle = (kernel32, handle)

    def _acquire_posix(self):
        import fcntl

        digest = hashlib.sha256(self.name.encode("utf-8")).hexdigest()[:20]
        lock_path = Path(tempfile.gettempdir()) / f"envaperu-pesaje-{digest}.lock"
        lock_file = lock_path.open("a+")

        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock_file.close()
            raise InstanceAlreadyRunning(self.name) from exc

        self._lock_file = lock_file

    def release(self):
        if self._handle is not None:
            kernel32, handle = self._handle
            kernel32.CloseHandle(handle)
            self._handle = None

        if self._lock_file is not None:
            import fcntl

            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()

