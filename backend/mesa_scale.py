"""Lector serial pasivo para la estación local de Mesa.

La evidencia disponible del Accura es una emisión continua a 9600/8N1, sin
handshake, con líneas ``ST,NT,+   0.40kg`` y ``ST,NT,+     46Pcs``. Este
adaptador no transmite comandos y no transforma Pcs en kg. ``GS`` se conserva
como base recibida si el equipo la emite; no se inventa desde ``NT``.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable

from mesa_logging import get_mesa_logger, log_event, log_peripheral_state

try:  # pyserial está disponible en el runtime de la estación.
    import serial
except ImportError:  # permite importar el backend en entornos de pruebas mínimos.
    serial = None


_LINE = re.compile(
    r"^\s*(?P<state>ST|US)\s*,\s*(?P<base>NT|GS)\s*,\s*(?P<sign>[+-])\s*"
    r"(?P<value>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>kg|Pcs)\s*$",
    re.IGNORECASE,
)
MAX_FRAME_BYTES = 256


@dataclass(frozen=True)
class AccuraReading:
    stable: bool
    base: str
    kg: str | None
    unit: str


def parse_accura_line(raw: bytes | str) -> AccuraReading | None:
    """Parsea una línea completa; devuelve ``None`` para una trama inválida."""

    if isinstance(raw, bytes):
        if not raw.endswith(b"\r\n"):
            return None
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError:
            return None
    else:
        if not raw.endswith("\r\n"):
            return None
        text = raw
    text = text.strip("\r\n")
    match = _LINE.fullmatch(text)
    if not match:
        return None
    state = match.group("state").upper()
    base = match.group("base").upper()
    unit = match.group("unit")
    unit = "kg" if unit.lower() == "kg" else "Pcs"
    sign = match.group("sign")
    try:
        value = Decimal(match.group("value"))
    except (InvalidOperation, ValueError):
        return None
    if sign == "-":
        value = -value
    if state != "ST" or unit != "kg" or value <= 0:
        return AccuraReading(stable=state == "ST", base=base, kg=None, unit=unit)
    # Preserve the display precision while normalizing harmless leading zeros.
    kg = format(value, "f")
    return AccuraReading(stable=True, base=base, kg=kg, unit="kg")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MesaScaleReader:
    """Escucha un Accura sin escribir nunca al puerto serial."""

    def __init__(
        self,
        port: str | None,
        *,
        configured: bool = True,
        baudrate: int = 9600,
        serial_factory: Callable | None = None,
        clock: Callable[[], datetime] = _now,
        freshness_seconds: float = 3.0,
    ):
        self.port = port
        self._configured = bool(configured and port)
        self.baudrate = baudrate
        self._serial_factory = serial_factory or (serial.Serial if serial else None)
        self._clock = clock
        self._freshness_seconds = freshness_seconds
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._serial = None
        self._available = False
        self._base: str | None = None
        self._kg: str | None = None
        self._message = (
            "Balanza Accura no conectada."
            if self._configured
            else "Configure el puerto COM de la Accura cuando conecte la balanza."
        )
        self._last_received_at: datetime | None = None
        self._last_received_monotonic: float | None = None
        self._buffer = bytearray()

    @property
    def is_available(self) -> bool:
        with self._lock:
            return self._available

    def status(self) -> dict:
        self._expire_if_stale()
        with self._lock:
            return {
                "modo": "accura",
                "disponible": self._available,
                "base": self._base,
                "kg": self._kg,
                "mensaje": self._message,
            }

    def start(self) -> bool:
        """Abre el puerto y comienza la escucha; no envía bytes."""

        if not self._configured:
            # A station may be installed before its physical Accura is known.
            # Do not open ``None`` and do not create a retry thread: manual
            # inventory weighing must remain blocked until configuration.
            self._stop.set()
            self._thread = None
            self._clear(
                "Configure el puerto COM de la Accura cuando conecte la balanza.",
                available=False,
            )
            log_peripheral_state(
                "accura",
                "unconfigured",
                component="mesa_scale",
                configured=False,
                available=False,
            )
            return False

        connected = False
        try:
            connection = self._open_connection()
            with self._lock:
                self._serial = connection
                self._available = True
                self._message = "Balanza Accura conectada; esperando lectura estable."
            log_peripheral_state("accura", "connected", component="mesa_scale", configured=True, available=True)
            connected = True
        except Exception as error:  # SerialException varies between pyserial backends.
            self._close_serial()
            self._clear(f"No se pudo conectar la balanza Accura: {error}", available=False)
            log_event(
                "recoverable_failure",
                logger=get_mesa_logger("scale"),
                component="mesa_scale",
                operation="open_serial",
                error_type=type(error).__name__,
                recoverable=True,
                retryable=True,
                physical_status="not_verified",
            )
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen, name="mesa-accura", daemon=True)
        self._thread.start()
        return connected

    def close(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        self._thread = None
        self._close_serial()
        self._clear(
            "Balanza Accura desconectada."
            if self._configured
            else "Configure el puerto COM de la Accura cuando conecte la balanza.",
            available=False,
        )
        log_peripheral_state(
            "accura",
            "closed",
            component="mesa_scale",
            configured=self._configured,
            available=False,
        )

    def snapshot_for(self, code: str, *, ttl_seconds: int = 30) -> dict:
        """Congela la última lectura positiva para una manga concreta."""

        self._expire_if_stale()
        with self._lock:
            kg = self._kg
            base = self._base
            available = self._available
            captured_at = self._last_received_at
        if not available:
            raise ValueError("La balanza Accura no está disponible")
        if not kg or not base or captured_at is None:
            raise ValueError("Espere una lectura estable positiva en kg")
        token = uuid.uuid4().hex
        return {
            "token": token,
            "codigo": code,
            "kg": kg,
            "base": base,
            "captured_at": captured_at,
            "expires_at": self._clock().timestamp() + ttl_seconds,
        }

    def feed_for_test(self, raw: bytes) -> None:
        """Inyecta una línea en pruebas sin abrir un puerto ni transmitir."""

        if not self._configured:
            return
        self._available = True
        self._feed_chunk(raw)

    def _listen(self) -> None:
        while not self._stop.is_set():
            if self._serial is None:
                self._reconnect("Balanza Accura no conectada; esperando reconexión.")
                continue
            try:
                chunk = self._serial.readline() if self._serial is not None else b""
                if not chunk:
                    continue
                self._feed_chunk(chunk)
            except Exception as error:
                if self._stop.is_set():
                    break
                self._reconnect(f"Balanza Accura desconectada: {error}")

    def _feed_chunk(self, chunk: bytes) -> None:
        self._buffer.extend(chunk)
        while b"\n" in self._buffer:
            line, _, remainder = self._buffer.partition(b"\n")
            self._buffer = bytearray(remainder)
            self._consume(bytes(line) + b"\n")
        if len(self._buffer) > MAX_FRAME_BYTES:
            self._buffer.clear()
            self._clear("Trama Accura demasiado larga; esperando CRLF.")

    def _consume(self, raw: bytes) -> None:
        reading = parse_accura_line(raw)
        if reading is None:
            self._clear("Trama Accura inválida; esperando una lectura completa.")
            log_peripheral_state("accura", "invalid_frame", component="mesa_scale", available=self.is_available)
            return
        if not reading.stable:
            self._clear("Lectura inestable; espere ST.")
            log_peripheral_state("accura", "unstable", component="mesa_scale", available=self.is_available)
            return
        if reading.unit == "Pcs":
            with self._lock:
                self._base = reading.base
                self._kg = None
                self._message = "La balanza está en conteo (Pcs); no se captura como kg."
                self._last_received_at = self._clock()
                self._last_received_monotonic = time.monotonic()
            log_peripheral_state("accura", "count_mode", component="mesa_scale", available=True, unit="Pcs", stable=True)
            return
        with self._lock:
            self._base = reading.base
            self._kg = reading.kg
            self._message = "Lectura Accura estable en kg." if reading.kg else "Peso no positivo; no se puede capturar."
            self._last_received_at = self._clock()
            self._last_received_monotonic = time.monotonic()
        log_peripheral_state("accura", "stable_kg", component="mesa_scale", available=True, unit="kg", stable=True)

    def _clear(self, message: str, *, available: bool | None = None) -> None:
        with self._lock:
            self._base = None
            self._kg = None
            self._message = message
            self._last_received_at = None
            self._last_received_monotonic = None
            if available is not None:
                self._available = available

    def _close_serial(self) -> None:
        connection = self._serial
        self._serial = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    def _expire_if_stale(self) -> None:
        with self._lock:
            received = self._last_received_monotonic
            active = self._kg is not None or self._base is not None
        if active and received is not None and time.monotonic() - received > self._freshness_seconds:
            self._clear("Lectura Accura vencida; esperando una lectura fresca.")
            log_peripheral_state("accura", "stale", component="mesa_scale", available=self.is_available)

    def _reconnect(self, message: str) -> None:
        self._close_serial()
        self._buffer.clear()
        self._clear(message, available=False)
        log_peripheral_state("accura", "disconnected", component="mesa_scale", available=False)
        while not self._stop.is_set():
            if self._stop.wait(1.0):
                return
            try:
                connection = self._open_connection()
                with self._lock:
                    self._serial = connection
                    self._available = True
                    self._message = "Balanza Accura reconectada; esperando lectura estable."
                log_peripheral_state("accura", "reconnected", component="mesa_scale", available=True)
                return
            except Exception as error:
                self._clear(f"Balanza Accura no disponible: {error}", available=False)
                log_event(
                    "recoverable_failure",
                    logger=get_mesa_logger("scale"),
                    component="mesa_scale",
                    operation="reconnect_serial",
                    error_type=type(error).__name__,
                    recoverable=True,
                    retryable=True,
                    physical_status="not_verified",
                )

    def _open_connection(self):
        if self._serial_factory is None:
            raise OSError("pyserial no está instalado")
        # Construct closed: DTR/RTS are low before assigning the COM and opening.
        connection = self._serial_factory(
            port=None, baudrate=self.baudrate, bytesize=8,
            parity="N", stopbits=1, timeout=0.25,
            xonxoff=False, rtscts=False, dsrdtr=False,
        )
        try:
            try:
                connection.dtr = False
                connection.rts = False
            except (AttributeError, OSError):
                pass
            if getattr(connection, "port", None) != self.port:
                connection.port = self.port
            opener = getattr(connection, "open", None)
            if callable(opener) and not getattr(connection, "is_open", False):
                opener()
            # Repeat after open because some Win32 drivers reset line state there.
            for name in ("dtr", "rts"):
                try:
                    setattr(connection, name, False)
                except (AttributeError, OSError):
                    pass
        except Exception:
            try:
                connection.close()
            except Exception:
                pass
            raise
        return connection


class ScaleCaptureError(ValueError):
    """Una captura física no puede usarse para esta operación."""


def validate_capture(connection, token: str, code: str, *, expected_kg: str | None = None) -> dict:
    """Valida una captura congelada, sin consumirla.

    La llamada debe ejecutarse dentro de la transacción de la operación que la
    consume. El token queda vinculado a la manga y caduca para evitar sustituir
    la lectura después de que el operador la haya confirmado.
    """

    row = connection.execute("SELECT * FROM mesa_scale_captures WHERE token = ?", (token,)).fetchone()
    if row is None:
        raise ScaleCaptureError("La captura de balanza no existe o ya fue utilizada")
    if row["codigo"] != code:
        raise ScaleCaptureError("La captura de balanza pertenece a otra manga")
    if row["used_at"] is not None:
        raise ScaleCaptureError("La captura de balanza ya fue utilizada")
    try:
        expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ScaleCaptureError("La captura de balanza tiene una caducidad inválida")
    if _now() >= expires:
        raise ScaleCaptureError("La captura de balanza caducó; repita la lectura")
    if expected_kg is not None and Decimal(str(row["kg"])) != Decimal(str(expected_kg)):
        raise ScaleCaptureError("El peso capturado cambió; repita la lectura")
    return dict(row)


def consume_capture(connection, token: str) -> None:
    connection.execute(
        "UPDATE mesa_scale_captures SET used_at = ? WHERE token = ? AND used_at IS NULL",
        (_now().isoformat(timespec="milliseconds").replace("+00:00", "Z"), token),
    )


__all__ = [
    "AccuraReading", "MesaScaleReader", "ScaleCaptureError", "consume_capture",
    "parse_accura_line", "validate_capture",
]
