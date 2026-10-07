const state = (kind, title, recovery = '') => ({ kind, title, recovery, ready: kind === 'ready' });

export function needsPrintRetry(result) {
  const printResult = result?.print_result || {};
  const status = String(printResult.result || printResult.estado || '').toUpperCase();
  return ['NOT_EMITTED', 'NO_EMITIDO', 'NO_EMITIDA'].includes(status)
    || printResult.error_code === 'PRINT_FORMAT_INVALID';
}

function legacyBlocker(context) {
  const manga = context.manga || {};
  if (manga.estado === 'ANULADA') {
    return state('blocked', 'Manga anulada', 'Solicite a Central revisar su identificación.');
  }
  if (context.weighing || ['PESADA', 'ETIQUETADA', 'RECIBIDA', 'PENDIENTE_RECEPCION_ALMACEN'].includes(manga.estado)) {
    return state('blocked', 'Manga cerrada', 'Escanee otra manga. Si el cierre fue incorrecto, solicite revisión en Central.');
  }
  if (manga.estado === 'CONTINUIDAD_PENDIENTE') {
    return state('blocked', 'Continuidad pendiente de vinculación', 'Solicite a Central revisar la continuidad. Conserve el mismo QR.');
  }
  if (['PLANIFICADO', 'PROGRAMADO'].includes(manga.trabajo_color?.estado)) {
    return state('blocked', 'Trabajo de la OT sin iniciar', 'Solicite a Central iniciar el Trabajo de la OT y vuelva a escanear.');
  }
  return state('blocked', 'Manga no habilitada para pesar', 'Solicite a Central revisar el estado de la manga y su Trabajo; después vuelva a escanear.');
}

// Button and F2 eligibility share this state. Central capabilities remain authoritative.
export function getWeighingState({ context, busy, result, centralAvailable, listening,
  controlOnly, peso, tare, net, lastControlNet, validPartialClose, partialClose, error,
  scanConsumed }) {
  if (needsPrintRetry(result) && !busy) return state(
    'print-retry',
    'Pesaje confirmado; etiqueta no emitida',
    'El pesaje ya est� guardado. Reintente solo la emisi�n con la misma operaci�n; no se releer� la balanza.',
  );
  if (busy) return state('waiting', 'Operación en curso', 'Espere la respuesta; no retire ni cambie la manga.');
  if (result) return state('success', 'Cierre registrado · manga cerrada', 'Revise el resultado de impresión y escanee la siguiente manga.');
  if (scanConsumed) return state(
    'success',
    'Pesaje registrado · escanee el siguiente QR',
    'Retire la manga de la balanza y escanee el QR del siguiente pesaje, aunque continúe con la misma manga.',
  );
  if (!centralAvailable) return state('blocked', 'Piloto SCM bloqueado: central sin conexión', 'Restablezca la conexión con Central y vuelva a escanear. No se puede registrar offline.');
  if (!context) return error
    ? state('error', 'Etiqueta no disponible', 'Revise el rechazo indicado y escanee una preetiqueta válida. No hay una manga seleccionada.')
    : state('waiting', 'Escanee el QR de PREPESAJE', 'El escaneo consulta la manga; no registra un pesaje.');
  const action = controlOnly ? 'registrar_avance_kg' : 'completar_final';
  const allowed = controlOnly ? context.can_register_weight_control : context.can_weigh;
  if (!allowed) {
    if (!controlOnly && context.can_register_weight_control) {
      return state(
        'waiting',
        'Seleccione control de peso para continuar',
        'Esta manga no admite cierre final en su estado actual. Marque Solo control de peso y vuelva a revisar F2.',
      );
    }
    const reason = context.bloqueos_pesaje?.[action]
      || context.bloqueos_pesaje?.completar_final
      || context.bloqueos_pesaje?.registrar_avance_kg;
    return reason ? state('blocked', reason.mensaje, reason.recuperacion) : legacyBlocker(context);
  }
  if (context.demo_only) return state('blocked', 'Vista de demostración · sin registro', 'Este QR permite revisar el contexto, pero no confirmar ni imprimir.');
  if (!listening) return state('blocked', 'Balanza desconectada', 'Conecte la balanza y compruebe la lectura antes de pesar.');
  if (!Number.isFinite(Number(peso)) || Number(peso) <= tare) {
    return state('waiting', 'Esperando peso neto válido', 'Coloque la manga y compruebe que el peso bruto sea mayor que la tara.');
  }
  // Contract precision is 0.001 kg, not an additional operational tolerance.
  if (lastControlNet > 0 && Math.round(net * 1000) <= Math.round(lastControlNet * 1000)) {
    return state('blocked', 'Sin aumento desde el último control', `Último neto: ${lastControlNet.toFixed(3)} kg. Verifique la manga y la lectura; solo registre cuando exista nuevo peso.`);
  }
  if (partialClose && !validPartialClose) {
    return state('blocked', 'Cierre parcial incompleto', 'Indique una cantidad menor a la asignada y el motivo del cierre parcial.');
  }
  if (error) return { ...state('error', 'Último intento sin confirmar',
    'Reintente con el mismo botón: se conserva la operación. Para revisar el estado en Central, vuelva a escanear.'), ready: true };
  return controlOnly
    ? state('ready', 'Listo para control de peso', 'Se registrarán kg acumulados. La manga continuará abierta, sin cambiar maquinista ni OT.')
    : state('ready', 'Listo para cierre final', 'F2 abrirá una confirmación antes de cerrar la manga.');
}

export function mangaStateLabel(value) {
  return ({ PREETIQUETADA: 'Abierta · preetiquetada', EN_LLENADO: 'Abierta · en llenado',
    CONTINUIDAD_PENDIENTE: 'Continuidad pendiente', PESADA: 'Cerrada · pesada',
    ETIQUETADA: 'Cerrada · etiquetada', PENDIENTE_RECEPCION_ALMACEN: 'Cerrada · pendiente de recepción',
    RECIBIDA: 'Cerrada · recibida', ANULADA: 'Anulada',
    CERRADA_ARMADO_PENDIENTE_PESAJE: 'Armado cerrado · pendiente de pesaje',
  })[value] || value?.replaceAll('_', ' ') || 'Estado no informado';
}
