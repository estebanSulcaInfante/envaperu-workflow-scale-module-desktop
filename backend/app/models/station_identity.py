from datetime import datetime, timezone

from app import db


def utc_now():
    return datetime.now(timezone.utc)


class StationIdentity(db.Model):
    __tablename__ = "station_identity"

    station_id = db.Column(db.String(36), primary_key=True)
    station_code = db.Column(db.String(50), nullable=False, unique=True)
    created_at_utc = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    provisioned_at_utc = db.Column(db.DateTime(timezone=True), nullable=True)

    runtime_state = db.relationship(
        "StationRuntimeState",
        back_populates="identity",
        uselist=False,
        cascade="all, delete-orphan",
    )


class StationRuntimeState(db.Model):
    __tablename__ = "station_runtime_state"

    station_id = db.Column(
        db.String(36),
        db.ForeignKey("station_identity.station_id", ondelete="CASCADE"),
        primary_key=True,
    )
    boot_id = db.Column(db.String(36), nullable=False)
    sequence = db.Column(db.Integer, nullable=False, default=0)
    started_at_utc = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    last_attempt_at_utc = db.Column(db.DateTime(timezone=True), nullable=True)
    last_central_ack_utc = db.Column(db.DateTime(timezone=True), nullable=True)
    last_heartbeat_id = db.Column(db.String(36), nullable=True)
    communication_state = db.Column(
        db.String(40),
        nullable=False,
        default="CENTRAL_NOT_PROVISIONED",
    )
    last_error_code = db.Column(db.String(100), nullable=True)
    next_heartbeat_seconds = db.Column(db.Integer, nullable=False, default=30)

    identity = db.relationship("StationIdentity", back_populates="runtime_state")

    def to_monitoring_dict(self):
        return {
            "station_id": self.station_id,
            "boot_id": self.boot_id,
            "sequence": self.sequence,
            "state": self.communication_state,
            "last_attempt_at_utc": (
                self.last_attempt_at_utc.isoformat()
                if self.last_attempt_at_utc
                else None
            ),
            "last_central_ack_utc": (
                self.last_central_ack_utc.isoformat()
                if self.last_central_ack_utc
                else None
            ),
            "last_error_code": self.last_error_code,
            "next_heartbeat_seconds": self.next_heartbeat_seconds,
        }
