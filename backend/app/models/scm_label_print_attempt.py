from datetime import datetime, timezone

from app import db


def utc_now():
    return datetime.now(timezone.utc)


class ScmLabelPrintAttempt(db.Model):
    """Local technical evidence; never an authoritative manga or weighing."""

    __tablename__ = "scm_label_print_attempt"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    print_job_id = db.Column(db.String(36), nullable=False, index=True)
    label_id = db.Column(db.String(36), nullable=False, index=True)
    label_type = db.Column(db.String(20), nullable=True)
    operation_id = db.Column(db.String(36), nullable=True, index=True)
    capture_id = db.Column(db.String(36), nullable=True)
    manga_id = db.Column(db.String(36), nullable=True, index=True)
    payload_hash = db.Column(db.String(64), nullable=False)
    rendered_payload_hash = db.Column(db.String(64), nullable=True)
    attempted_at_utc = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    completed_at_utc = db.Column(db.DateTime(timezone=True), nullable=True)
    printer_name = db.Column(db.String(160), nullable=True)
    result = db.Column(db.String(32), nullable=False)
    error_detail = db.Column(db.String(500), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "print_job_id": self.print_job_id,
            "label_id": self.label_id,
            "label_type": self.label_type,
            "operation_id": self.operation_id,
            "capture_id": self.capture_id,
            "manga_id": self.manga_id,
            "payload_hash": self.payload_hash,
            "rendered_payload_hash": self.rendered_payload_hash,
            "attempted_at_utc": self.attempted_at_utc.isoformat(),
            "completed_at_utc": (
                self.completed_at_utc.isoformat()
                if self.completed_at_utc else None
            ),
            "printer_name": self.printer_name,
            "result": self.result,
            "error_detail": self.error_detail,
        }
