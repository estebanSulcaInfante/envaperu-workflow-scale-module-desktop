const STATUS_COPY = {
  ONLINE: 'Central en línea',
  CENTRAL_NOT_PROVISIONED: 'Central sin provisionar',
  CENTRAL_UNREACHABLE: 'Central sin conexión',
  AUTH_ERROR: 'Credencial central rechazada',
  CENTRAL_INCOMPATIBLE: 'Central incompatible',
  CONTRACT_CONFLICT: 'Contrato central en conflicto',
  PAYLOAD_REJECTED: 'Heartbeat rechazado',
  RATE_LIMITED: 'Central temporalmente limitada',
  CENTRAL_ERROR: 'Central con incidencia',
  TLS_ERROR: 'Conexión central no segura'
};

function badgeClass(state) {
  if (state === 'ONLINE') return 'central-online';
  if (state === 'CENTRAL_NOT_PROVISIONED') return 'central-not-provisioned';
  return 'central-degraded';
}

export default function CentralStatusBadge({ state }) {
  const normalized = state || 'CENTRAL_NOT_PROVISIONED';
  const label = STATUS_COPY[normalized] || 'Central con incidencia';

  return (
    <div
      className={`connection-badge central-badge ${badgeClass(normalized)}`}
      role="status"
      aria-label={label}
      title={label}
    >
      <span className="status-dot" aria-hidden="true" />
      {label}
    </div>
  );
}
