import os
from pathlib import Path


class StationTokenStoreError(RuntimeError):
    pass


class StationTokenStore:
    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def _win32crypt():
        if os.name != "nt":
            raise StationTokenStoreError("DPAPI solo esta disponible en Windows")
        try:
            import win32crypt
        except ImportError as exc:
            raise StationTokenStoreError("win32crypt no esta disponible") from exc
        return win32crypt

    def read(self):
        if not self.path.is_file():
            return None
        encrypted = self.path.read_bytes()
        try:
            clear = self._win32crypt().CryptUnprotectData(
                encrypted,
                None,
                None,
                None,
                0,
            )[1]
        except Exception as exc:
            raise StationTokenStoreError("No se pudo descifrar el token") from exc
        token = clear.decode("utf-8").strip()
        return token or None

    def write(self, token):
        token = str(token or "").strip()
        if not token:
            raise ValueError("token es requerido")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = self._win32crypt().CryptProtectData(
            token.encode("utf-8"),
            "EnvaPeru weighing station token",
            None,
            None,
            None,
            0,
        )
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(encrypted)
        temporary.replace(self.path)


def read_configured_station_token(app):
    provider = app.config.get("STATION_TOKEN_PROVIDER")
    if provider is not None:
        return provider()
    token_file = app.config.get("STATION_TOKEN_FILE")
    if not token_file:
        return None
    return StationTokenStore(token_file).read()
