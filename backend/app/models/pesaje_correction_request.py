import json
from datetime import datetime, timezone

from app import db


class PesajeCorrectionRequest(db.Model):
    __tablename__ = "pesaje_correction_requests"

    ACTION_CORRECT = "CORRECT"
    ACTION_VOID = "VOID"
    PENDING_LOCAL_REVIEW = "PENDING_LOCAL_REVIEW"
    REQUIRES_CENTRAL_REVIEW = "REQUIRES_CENTRAL_REVIEW"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(36), nullable=False, unique=True)
    request_payload_hash = db.Column(db.String(64), nullable=False)
    pesaje_id = db.Column(
        db.Integer,
        db.ForeignKey("pesajes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    requested_at_utc = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    requested_by = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    evidence_reference = db.Column(db.String(500), nullable=True)
    proposed_changes_json = db.Column(db.Text, nullable=False)
    original_snapshot_json = db.Column(db.Text, nullable=False)
    source_classification = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), nullable=False)

    pesaje = db.relationship("Pesaje", back_populates="correction_requests")

    @staticmethod
    def _decode(value):
        return json.loads(value) if value else {}

    @property
    def proposed_changes(self):
        return self._decode(self.proposed_changes_json)

    @property
    def original_snapshot(self):
        return self._decode(self.original_snapshot_json)

    def to_dict(self):
        return {
            "id": self.id,
            "request_id": self.request_id,
            "pesaje_id": self.pesaje_id,
            "requested_at_utc": (
                self.requested_at_utc.isoformat()
                if self.requested_at_utc
                else None
            ),
            "requested_by": self.requested_by,
            "action": self.action,
            "reason": self.reason,
            "evidence_reference": self.evidence_reference,
            "proposed_changes": self.proposed_changes,
            "original_snapshot": self.original_snapshot,
            "source_classification": self.source_classification,
            "status": self.status,
        }
