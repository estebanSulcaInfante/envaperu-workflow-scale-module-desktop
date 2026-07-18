from datetime import datetime, timezone

from app import db


class PrintAttempt(db.Model):
    __tablename__ = "print_attempts"

    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"

    id = db.Column(db.Integer, primary_key=True)
    pesaje_id = db.Column(
        db.Integer,
        db.ForeignKey("pesajes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attempted_at_utc = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at_utc = db.Column(db.DateTime, nullable=True)
    printer_name = db.Column(db.String(100), nullable=True)
    result = db.Column(db.String(20), nullable=False, default=PENDING)
    error_code = db.Column(db.String(50), nullable=True)
    error_detail = db.Column(db.String(200), nullable=True)

    pesaje = db.relationship("Pesaje", back_populates="print_attempts")

    def to_dict(self):
        return {
            "id": self.id,
            "pesaje_id": self.pesaje_id,
            "attempted_at_utc": (
                self.attempted_at_utc.isoformat()
                if self.attempted_at_utc
                else None
            ),
            "completed_at_utc": (
                self.completed_at_utc.isoformat()
                if self.completed_at_utc
                else None
            ),
            "printer_name": self.printer_name,
            "result": self.result,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
        }
