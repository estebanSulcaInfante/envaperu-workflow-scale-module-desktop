import hashlib
import os
import tempfile
import time
from pathlib import Path


EVENT_MODIFY_STATE = 0x0002
ERROR_FILE_NOT_FOUND = 2
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258


def _safe_station_id(station_id):
    from app.runtime.single_instance import _safe_station_id as normalize

    return normalize(station_id)


def stop_event_name(station_id):
    return f"Local\\EnvaPeruPesajeStop-{_safe_station_id(station_id)}"


def _fallback_paths(station_id):
    digest = hashlib.sha256(stop_event_name(station_id).encode("utf-8")).hexdigest()[:20]
    root = Path(tempfile.gettempdir())
    return (
        root / f"envaperu-pesaje-{digest}.owner",
        root / f"envaperu-pesaje-{digest}.stop",
    )


class StationStopSignal:
    def __init__(self, station_id):
        self.station_id = _safe_station_id(station_id)
        self.name = stop_event_name(self.station_id)
        self._handle = None
        self._owner_path = None
        self._stop_path = None

        if os.name == "nt":
            self._create_windows_event()
        else:
            self._create_fallback_signal()

    def _create_windows_event(self):
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateEventW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateEventW(None, True, False, self.name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle = (kernel32, handle)

    def _create_fallback_signal(self):
        owner_path, stop_path = _fallback_paths(self.station_id)
        stop_path.unlink(missing_ok=True)
        owner_path.write_text(str(os.getpid()), encoding="ascii")
        self._owner_path = owner_path
        self._stop_path = stop_path

    def wait(self, timeout):
        if self._handle is not None:
            kernel32, handle = self._handle
            timeout_ms = max(0, int(timeout * 1000))
            result = kernel32.WaitForSingleObject(handle, timeout_ms)
            if result == WAIT_OBJECT_0:
                return True
            if result == WAIT_TIMEOUT:
                return False
            import ctypes

            raise ctypes.WinError(ctypes.get_last_error())

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stop_path.exists():
                return True
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        return self._stop_path.exists()

    def close(self):
        if self._handle is not None:
            kernel32, handle = self._handle
            kernel32.CloseHandle(handle)
            self._handle = None

        if self._owner_path is not None:
            self._owner_path.unlink(missing_ok=True)
            self._owner_path = None
        if self._stop_path is not None:
            self._stop_path.unlink(missing_ok=True)
            self._stop_path = None


def signal_station_stop(station_id):
    station_id = _safe_station_id(station_id)
    if os.name != "nt":
        owner_path, stop_path = _fallback_paths(station_id)
        if not owner_path.is_file():
            return False
        stop_path.touch()
        return True

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, stop_event_name(station_id))
    if not handle:
        error = ctypes.get_last_error()
        if error == ERROR_FILE_NOT_FOUND:
            return False
        raise ctypes.WinError(error)

    try:
        if not kernel32.SetEvent(handle):
            raise ctypes.WinError(ctypes.get_last_error())
        return True
    finally:
        kernel32.CloseHandle(handle)

