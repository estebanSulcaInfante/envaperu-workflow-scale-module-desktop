from dataclasses import dataclass
from datetime import datetime, timezone

from flask import current_app

from app import db
from app.models.print_attempt import PrintAttempt
from app.services.sticker_service import get_sticker_service


@dataclass(frozen=True)
class PrintOutcome:
    attempt: PrintAttempt
    status: str


def _error_detail(exc):
    detail = f"{type(exc).__name__}: {exc}"
    return detail[:200]


def execute_print_attempt(pesaje):
    attempt = PrintAttempt(
        pesaje=pesaje,
        printer_name=(
            current_app.config.get("PRINTER_NAME")
            or current_app.config.get("PRINTER_PORT")
        ),
        result=PrintAttempt.PENDING,
    )
    db.session.add(attempt)
    db.session.commit()

    try:
        sticker_service = current_app.config.get("STICKER_SERVICE")
        if sticker_service is None:
            sticker_service = get_sticker_service()
        success = bool(sticker_service.print_sticker(pesaje))
        if success:
            attempt.result = PrintAttempt.SUCCEEDED
            pesaje.sticker_impreso = True
            pesaje.fecha_impresion = datetime.now(timezone.utc)
        else:
            attempt.result = PrintAttempt.FAILED
            attempt.error_code = "PRINTER_REJECTED"
            attempt.error_detail = "Printer did not confirm the job"
    except Exception as exc:
        attempt.result = PrintAttempt.FAILED
        attempt.error_code = "PRINTER_EXCEPTION"
        attempt.error_detail = _error_detail(exc)

    attempt.completed_at_utc = datetime.now(timezone.utc)
    db.session.commit()
    return PrintOutcome(attempt=attempt, status=pesaje.print_status)
