"""POST copy jobs: online authorization, durable reservation, evidence-only recovery."""
import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.scm_post_reprint import ScmPostReprintJournal, ScmPostReprintEvent
from app.services.scm_prelabel_service import ScmPrelabelService, _station_timezone
from app.services.printer_service import get_printer_service


class PostReprintRenderer:
    VERSION = 'POSTPESAJE_COPY_TSPL_1'

    def render(self, job):
        if job.get('job_kind') != 'POSTPESAJE_COPY' or job.get('renderer_version') != self.VERSION:
            raise ValueError('Contrato de copia no compatible')
        payload = job.get('payload') or {}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
        if hashlib.sha256(canonical.encode('utf-8')).hexdigest() != job.get('payload_hash'):
            raise ValueError('Hash de fuente no coincide')
        for key in ('copy_job_id', 'source_label_id', 'source_pesaje_id'):
            UUID(str(job.get(key)))
        if re.search(r'[\x00-\x1f\x7f]', ''.join(self._strings(payload))):
            raise ValueError('La fuente contiene controles no imprimibles')
        if payload.get('document_type') != 'POSTPESAJE' or payload.get('qr'):
            raise ValueError('Solo se admiten comprobantes POSTPESAJE sin QR nuevo')
        if (payload.get('template') or {}).get('version') != 'POSTPESAJE_TSPL_5':
            raise ValueError('Plantilla fuente no compatible; requiere revision')
        copies = job.get('copias')
        if isinstance(copies, bool) or not isinstance(copies, int) or copies < 1:
            raise ValueError('Cantidad de copias invalida')
        # Safety ceiling is a protocol bound, not an implicit plant quota.
        if copies > 50:
            raise ValueError('El protocolo admite hasta 50 copias por trabajo')
        renderer = ScmPrelabelService()
        label = {'payload': payload, 'tipo': 'POSTPESAJE'}
        stamp = datetime.now(timezone.utc).astimezone(_station_timezone('America/Lima')).strftime('%d/%m/%Y %H:%M')
        pages, sheets = [], []
        for offset in range(0, copies, 2):
            pages.append('CLS')
            columns = []
            for slot in range(min(2, copies-offset)):
                x = renderer.LEFT_X if slot == 0 else renderer.RIGHT_X
                pages.append(renderer._column(x, label, stamp))
                columns.append(renderer._svg_column(x, label, stamp))
            pages.append('PRINT 1,1')
            sheets.append(f'<g transform="translate(0,{offset//2*400})">' + ''.join(columns) + '</g>')
        tspl = '\n'.join(['SIZE 109 mm, 50 mm', 'GAP 3 mm, 0 mm', 'SET REFERENCE 0,0',
                          'DIRECTION 1', 'SET TEAR ON', 'OFFSET 0 mm', 'CODEPAGE UTF-8', *pages]) + '\r\n'
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 872 %s">%s</svg>' % (((copies+1)//2)*400, ''.join(sheets))
        return tspl, svg

    @classmethod
    def _strings(cls, value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from cls._strings(child)
        elif isinstance(value, list):
            for child in value:
                yield from cls._strings(child)


class PostReprintService:
    def __init__(self, *, client=None, printer=None):
        self.client = client
        self.printer = printer

    def _client(self):
        return self.client or ScmPrelabelService._central_client()

    @staticmethod
    def _event(row, event, evidence=None):
        db.session.add(ScmPostReprintEvent(copy_job_id=row.copy_job_id, event=event,
                                         evidence_json=json.dumps(evidence) if evidence else None))

    @staticmethod
    def _enabled():
        if not current_app.config.get('SCM_POST_REPRINT_ENABLED', False):
            raise ValueError('Reimpresion POSTPESAJE no habilitada en esta estacion')

    def _view(self, row):
        evidence = json.loads(row.evidence_json) if row.evidence_json else {}
        return {'copy_job_id': row.copy_job_id, 'attempt_id': row.attempt_id,
                'result': evidence.get('result', 'UNCERTAIN'), 'state': row.state,
                'ack_pending': row.ack_pending, 'evidence': evidence,
                'physical_status': 'NO_CONFIRMADO'}

    def _ack(self, row):
        # No fallback to print. Offline delivery stores evidence for the next explicit sync.
        if row.evidence_json and row.ack_pending:
            try:
                self._client().ack_post_reprint_job(row.station_id, row.copy_job_id,
                                                   json.loads(row.evidence_json))
            except Exception:
                db.session.rollback()
            else:
                row.ack_pending = False
                self._event(row, 'ACKED')
                db.session.commit()
        return self._view(row)

    def sync_evidence(self):
        self._enabled()
        rows = ScmPostReprintJournal.query.filter_by(ack_pending=True).all()
        return {'jobs': [self._ack(row) for row in rows]}

    def list_jobs(self):
        self._enabled()
        return self._client().list_post_reprint_jobs(ScmPrelabelService._station_id())

    def execute(self, copy_job_id):
        self._enabled()
        row = db.session.get(ScmPostReprintJournal, copy_job_id)
        if row:
            return self._ack(row)
        row = ScmPostReprintJournal(copy_job_id=copy_job_id, attempt_id=str(uuid4()),
                                   station_id=ScmPrelabelService._station_id(), state='RESERVED')
        db.session.add(row)
        self._event(row, 'RESERVED')
        try:
            db.session.commit()  # Unique job reservation is durable BEFORE even claiming central.
        except IntegrityError:
            db.session.rollback()
            return self._view(db.session.get(ScmPostReprintJournal, copy_job_id))
        try:
            job = self._client().claim_post_reprint_job(row.station_id, copy_job_id, row.attempt_id)
        except Exception:
            # Claim may have succeeded remotely. Never infer that paper can be retried.
            return self._view(row)
        try:
            if str(job.get('copy_job_id')) != str(copy_job_id):
                raise ValueError('Identidad del trabajo no coincide')
            tspl, _ = PostReprintRenderer().render(job)
        except (ValueError, KeyError, TypeError) as exc:
            evidence = {'attempt_id': row.attempt_id, 'result': 'NOT_EMITTED', 'error': str(exc),
                        'expected_bytes': 0, 'bytes_written': 0, 'write_attempted': False}
        else:
            row.job_json = json.dumps(job, sort_keys=True)
            row.tspl = tspl
            row.state = 'EMITTING'
            self._event(row, 'EMITTING', {'rendered_payload_hash': hashlib.sha256(tspl.encode()).hexdigest()})
            db.session.commit()  # Durable payload and reservation before the first printer byte.
            printer = self.printer or current_app.config.get('SCM_POST_REPRINT_PRINTER') or get_printer_service()
            try:
                emission = printer.print_tspl_result(tspl).to_dict()
                result = emission.pop('status')
                if result not in {'ACCEPTED', 'NOT_EMITTED', 'UNCERTAIN'}:
                    result = 'UNCERTAIN'
            except Exception as exc:
                emission, result = {'error': str(exc)[:500]}, 'UNCERTAIN'
            evidence = {**emission, 'attempt_id': row.attempt_id, 'result': result,
                        'rendered_payload_hash': hashlib.sha256(tspl.encode()).hexdigest(),
                        'renderer_version': PostReprintRenderer.VERSION,
                        'printer_name': getattr(printer, 'printer_name', None)}
        row.state = evidence['result']
        row.evidence_json = json.dumps(evidence, sort_keys=True)
        self._event(row, row.state, evidence)
        db.session.commit()
        return self._ack(row)
