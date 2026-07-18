const COPY = {
  SAVED_PRINTED: {
    title: 'Pesaje guardado e impreso',
    detail: 'El registro y su etiqueta quedaron confirmados.',
  },
  SAVED_PRINT_PENDING: {
    title: 'Pesaje guardado; impresi\u00f3n pendiente',
    detail: 'El registro existe. Puede reintentar solo la etiqueta.',
  },
  SAVED_PRINT_FAILED: {
    title: 'Pesaje guardado; impresi\u00f3n fallida',
    detail: 'No repita el pesaje. Reintente \u00fanicamente la impresi\u00f3n.',
  },
};

function CaptureResultNotice({ result, onRetryPrint, retrying = false }) {
  if (!result) return null;

  const status = result.status || result.printStatus;
  const copy = COPY[status] || COPY.SAVED_PRINT_PENDING;
  const pesaje = result.pesaje || {};
  const canRetry = status !== 'SAVED_PRINTED' && pesaje.capture_id;

  return (
    <section
      className={`capture-result-notice ${status.toLowerCase()}`}
      aria-live="polite"
      role={status === 'SAVED_PRINT_FAILED' ? 'alert' : 'status'}
    >
      <div className="capture-result-copy">
        <strong>{copy.title}</strong>
        <span>
          Pesaje #{pesaje.id} · {Number(pesaje.peso_kg || 0).toFixed(3)} kg
        </span>
        <small>{copy.detail}</small>
      </div>
      {canRetry && (
        <button
          type="button"
          className="btn btn-secondary capture-retry-button"
          aria-label={'Reintentar impresi\u00f3n'}
          onClick={() => onRetryPrint(pesaje.capture_id)}
          disabled={retrying}
        >
          {retrying ? 'Reintentando...' : 'Reintentar impresi\u00f3n'}
        </button>
      )}
    </section>
  );
}

export default CaptureResultNotice;
