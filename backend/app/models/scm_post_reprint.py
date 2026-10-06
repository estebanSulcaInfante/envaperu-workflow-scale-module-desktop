"""Technical copy journal, independent of weighing and original label state."""
from datetime import datetime, timezone
from app import db


class ScmPostReprintJournal(db.Model):
    __tablename__ = 'scm_post_reprint_journal'
    copy_job_id = db.Column(db.String(36), primary_key=True)
    attempt_id = db.Column(db.String(36), nullable=False, unique=True)
    station_id = db.Column(db.String(36), nullable=False)
    state = db.Column(db.String(32), nullable=False)
    job_json = db.Column(db.Text)
    tspl = db.Column(db.Text)
    evidence_json = db.Column(db.Text)
    ack_pending = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ScmPostReprintEvent(db.Model):
    __tablename__ = 'scm_post_reprint_event'
    id = db.Column(db.Integer, primary_key=True)
    copy_job_id = db.Column(db.String(36), nullable=False, index=True)
    event = db.Column(db.String(32), nullable=False)
    evidence_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
