import ipaddress
import uuid
from urllib.parse import urlencode, urlparse

import requests


class CentralApiError(RuntimeError):
    def __init__(self, state, message, *, retry_after=None):
        super().__init__(message)
        self.state = state
        self.retry_after = retry_after


def _is_loopback_host(hostname):
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def normalize_central_origin(origin, *, allow_insecure=False):
    value = str(origin or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("CENTRAL_ORIGIN debe ser un origen HTTP(S) valido")
    if parsed.username or parsed.password:
        raise ValueError("CENTRAL_ORIGIN no admite credenciales")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("CENTRAL_ORIGIN no admite path, query ni fragment")
    if (
        parsed.scheme == "http"
        and not _is_loopback_host(parsed.hostname)
        and not allow_insecure
    ):
        raise ValueError(
            "CENTRAL_ORIGIN remoto requiere HTTPS o "
            "ALLOW_INSECURE_CENTRAL=true para una LAN controlada"
        )
    return f"{parsed.scheme}://{parsed.netloc}"


class CentralApiClient:
    CONNECT_TIMEOUT_SECONDS = 3.0
    READ_TIMEOUT_SECONDS = 5.0
    CAPABILITIES_READ_TIMEOUT_SECONDS = 30.0
    LEGACY_HISTORY_READ_TIMEOUT_SECONDS = 120.0

    def __init__(
        self,
        origin,
        token,
        station_version,
        session=None,
        *,
        allow_insecure=False,
    ):
        self.origin = normalize_central_origin(
            origin,
            allow_insecure=allow_insecure,
        )
        self._token = token
        self.station_version = station_version
        self.session = session or requests.Session()

    def __repr__(self):
        return (
            f"CentralApiClient(origin={self.origin!r}, "
            f"station_version={self.station_version!r})"
        )

    def _headers(self, idempotency_key=None):
        headers = {
            "Authorization": f"Bearer {self._token}",
            "User-Agent": f"EnvaPeru-Weighing-Station/{self.station_version}",
            "X-Station-Version": self.station_version,
            "X-Correlation-Id": str(uuid.uuid4()),
            "Accept": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    @staticmethod
    def _state_for_status(status_code, operation):
        if status_code in {401, 403}:
            return "AUTH_ERROR"
        if status_code == 404:
            return "CENTRAL_INCOMPATIBLE"
        if status_code == 409:
            return "CONTRACT_CONFLICT"
        if status_code == 422:
            return "PAYLOAD_REJECTED"
        if status_code == 429:
            return "RATE_LIMITED"
        if 500 <= status_code <= 599:
            return "CENTRAL_ERROR"
        return "CENTRAL_ERROR"

    def _request(
        self,
        method,
        path,
        *,
        operation,
        payload=None,
        idempotency_key=None,
        read_timeout=None,
    ):
        effective_read_timeout = (
            self.READ_TIMEOUT_SECONDS if read_timeout is None else read_timeout
        )
        try:
            response = self.session.request(
                method,
                f"{self.origin}{path}",
                headers=self._headers(idempotency_key),
                json=payload,
                timeout=(
                    self.CONNECT_TIMEOUT_SECONDS,
                    effective_read_timeout,
                ),
            )
        except requests.exceptions.SSLError as exc:
            raise CentralApiError("TLS_ERROR", "TLS validation failed") from exc
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            raise CentralApiError(
                "CENTRAL_UNREACHABLE",
                f"Central connection failed ({type(exc).__name__})",
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise CentralApiError(
                "CENTRAL_UNREACHABLE",
                "Central request failed",
            ) from exc

        if response.status_code != 200:
            retry_after = response.headers.get("Retry-After")
            central_message = None
            try:
                error_payload = response.json()
                if isinstance(error_payload, dict):
                    nested = error_payload.get("error")
                    if isinstance(nested, dict):
                        central_message = nested.get("message")
                    if not central_message:
                        central_message = error_payload.get("message")
            except (ValueError, TypeError):
                central_message = None
            raise CentralApiError(
                self._state_for_status(response.status_code, operation),
                str(central_message or (
                    f"Central rejected {operation} with HTTP {response.status_code}"
                )),
                retry_after=retry_after,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise CentralApiError(
                "CENTRAL_INCOMPATIBLE",
                f"Central returned non-JSON for {operation}",
            ) from exc

    def get_capabilities(self):
        return self._request(
            "GET",
            "/api/integration/v1/capabilities",
            operation="capabilities",
            read_timeout=self.CAPABILITIES_READ_TIMEOUT_SECONDS,
        )

    def send_heartbeat(self, station_id, payload):
        return self._request(
            "PUT",
            f"/api/integration/v1/stations/{station_id}/heartbeat",
            operation="heartbeat",
            payload=payload,
            idempotency_key=payload["heartbeat_id"],
        )

    def send_production_progress(self, station_id, payload):
        return self._request(
            "PUT",
            f"/api/integration/v1/stations/{station_id}/production-progress",
            operation="production_progress",
            payload=payload,
            idempotency_key=payload["report_id"],
        )

    def get_scm_print_job(self, station_id, print_job_id):
        return self._request(
            "GET",
            (
                f"/api/integration/v1/stations/{station_id}/"
                f"print-jobs/{print_job_id}"
            ),
            operation="scm_prelabel_print_job",
        )

    def list_scm_print_jobs(self, station_id, *, status="PENDING", limit=20):
        query = urlencode({"status": status, "limit": limit})
        return self._request(
            "GET",
            (
                f"/api/integration/v1/stations/{station_id}/"
                f"print-jobs?{query}"
            ),
            operation="scm_prelabel_print_jobs",
        )

    def claim_scm_print_job(self, station_id, print_job_id):
        return self._request(
            "POST",
            (
                f"/api/integration/v1/stations/{station_id}/"
                f"print-jobs/{print_job_id}/claim"
            ),
            operation="scm_prelabel_print_job_claim",
            idempotency_key=print_job_id,
        )

    def resolve_scm_manga_label(self, label_id):
        return self._request(
            "GET",
            f"/api/integration/v1/manga-labels/{label_id}/resolve",
            operation="scm_manga_label_resolve",
        )

    def confirm_scm_manga_weighing(self, operation_id, payload):
        return self._request(
            "POST",
            "/api/integration/v1/manga-weighings",
            operation="scm_manga_weighing",
            payload=payload,
            idempotency_key=operation_id,
        )

    def record_scm_manga_weighing_control(self, operation_id, payload):
        return self._request(
            "POST",
            "/api/integration/v1/manga-weighing-controls",
            operation="scm_manga_weighing_control",
            payload=payload,
            idempotency_key=operation_id,
        )

    def capture_inventory_opening_unit(self, station_id, operation_id, payload):
        return self._request(
            "POST",
            f"/api/integration/v1/stations/{station_id}/inventory-opening-units",
            operation="scm_inventory_opening_weighing",
            payload=payload,
            idempotency_key=operation_id,
        )

    def resolve_inventory_opening_target(self, station_id, payload):
        return self._request(
            "POST",
            f"/api/integration/v1/stations/{station_id}/inventory-opening-targets/resolve",
            operation="scm_inventory_opening_target_resolve",
            payload=payload,
        )

    def capture_prepared_material_reading(self, station_id, operation_id, payload):
        return self._request(
            "POST",
            f"/api/integration/v1/stations/{station_id}/prepared-material-readings",
            operation="scm_prepared_material_weighing",
            payload=payload,
            idempotency_key=operation_id,
        )

    def resolve_prepared_material_source_unit(self, station_id, payload):
        return self._request(
            "POST",
            f"/api/integration/v1/stations/{station_id}/prepared-material-source-units/resolve",
            operation="scm_prepared_material_source_resolve",
            payload=payload,
        )

    def get_scm_operation(self, operation_id):
        return self._request(
            "GET",
            f"/api/integration/v1/operations/{operation_id}",
            operation="scm_operation_recovery",
        )

    def acknowledge_scm_print_job(
        self, station_id, print_job_id, payload
    ):
        return self._request(
            "PUT",
            (
                f"/api/integration/v1/stations/{station_id}/"
                f"print-jobs/{print_job_id}/result"
            ),
            operation="scm_prelabel_print_result",
            payload=payload,
            idempotency_key=print_job_id,
        )

    def send_legacy_history_chunk(
        self,
        station_id,
        import_id,
        chunk_index,
        payload,
    ):
        return self._request(
            "PUT",
            (
                f"/api/integration/v1/stations/{station_id}/legacy-history/"
                f"imports/{import_id}/chunks/{chunk_index}"
            ),
            operation="legacy_history",
            payload=payload,
            idempotency_key=f"{import_id}:{chunk_index}",
            read_timeout=self.LEGACY_HISTORY_READ_TIMEOUT_SECONDS,
        )

    def get_history_sync_state(self, station_id):
        return self._request(
            "GET",
            f"/api/integration/v1/stations/{station_id}/legacy-history/sync-state",
            operation="legacy_history_sync_state",
        )

    def send_history_delta(self, station_id, payload):
        return self._request(
            "PUT",
            (
                f"/api/integration/v1/stations/{station_id}/legacy-history/"
                f"deltas/{payload['batch_id']}"
            ),
            operation="legacy_history_delta",
            payload=payload,
            idempotency_key=payload["batch_id"],
            read_timeout=self.LEGACY_HISTORY_READ_TIMEOUT_SECONDS,
        )

    def get_pilot_commands(self, station_id):
        return self._request(
            "GET",
            f"/api/integration/v1/stations/{station_id}/pilot-commands",
            operation="pilot_commands",
        )

    def acknowledge_pilot_command(self, station_id, command_id, payload):
        return self._request(
            "POST",
            (
                f"/api/integration/v1/stations/{station_id}/"
                f"pilot-commands/{command_id}/ack"
            ),
            operation="pilot_command_ack",
            payload=payload,
        )
