# Actualización de la PC de pesaje — piloto SCM

Este procedimiento instala `1.2.0-pilot.3` sin modificar la base antigua a
ciegas. El paquete es inmutable, funciona sin Internet para instalar sus
dependencias y conserva código, datos, configuración y secretos en ubicaciones
separadas.

## Gate de salida

No habilitar pesajes productivos hasta obtener y registrar todos estos hitos:

- `PILOT_CONFIG_READY`;
- `CENTRAL_ONLINE`;
- `UPDATE_COMPLETE` o `LEGACY_MIGRATION_COMPLETE`;
- `/health/ready` con `status=READY` y `central.state=ONLINE`;
- historial anterior visible y conteos conciliados;
- balanza real, impresora real, dos stickers iguales y QR escaneado con Enter;
- arranque de la tarea programada con el mismo usuario que provisionó el token.

La respuesta `READY` por sí sola no acredita Central ni el hardware.

## 1. Antes de ir a la PC

Llevar en una misma carpeta de soporte:

- `envaperu-pesaje-1.2.0-pilot.3-win-x64.zip`;
- `envaperu-pesaje-1.2.0-pilot.3-win-x64.zip.sha256`;
- este runbook;
- el SHA-256 comunicado por un segundo canal;
- UUID real de la estación en Central;
- ID numérico del trabajador que operará el piloto;
- token de esa misma estación;
- cuenta Windows operativa que inicia la estación.

Central debe estar desplegado y compatible antes de activar la estación. El
paquete no está firmado con Authenticode; durante el piloto solo se distribuye
por el canal privado acordado y siempre se compara el SHA-256.

## 2. Ventana operativa

Antes de detener la versión anterior, terminar o conciliar:

- pesaje o lectura activa en pantalla;
- manga abierta sin entrega de continuidad;
- preetiqueta o sticker pendiente;
- impresión `PENDING`, `EMISION_EN_PROGRESO`, `EMISION_INCIERTA` o `PARCIAL`;
- impresión exitosa cuyo acuse central siga pendiente;
- operación SCM resuelta localmente pero aún no confirmada.

Cerrar el navegador operativo y deshabilitar temporalmente cualquier arranque
automático de la aplicación antigua. No actualizar durante producción.

## 3. Verificar el paquete y extraerlo

Abrir Windows PowerShell 5.1 como administrador, usando la **misma cuenta
Windows que operará la estación**:

```powershell
$Kit = 'C:\Soporte\EnvaPeru-Piloto-1.2.0-pilot.3'
$Zip = Join-Path $Kit 'envaperu-pesaje-1.2.0-pilot.3-win-x64.zip'
certutil -hashfile $Zip SHA256
```

El hash debe coincidir exactamente con el `.sha256` y con el valor recibido por
el segundo canal. **Solo después de confirmar esa coincidencia**, desbloquear el
ZIP, extraerlo y desbloquear los scripts contenidos:

```powershell
Unblock-File -LiteralPath $Zip
Expand-Archive -LiteralPath $Zip -DestinationPath (Join-Path $Kit 'extraido')
Get-ChildItem -LiteralPath (Join-Path $Kit 'extraido\release') `
  -Filter '*.ps1' -File | Unblock-File
```

No cambiar la política global con `Set-ExecutionPolicy Unrestricted`. Si la
política corporativa impide `Unblock-File`, soporte puede invocar cada script
verificado con `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ...`;
ese bypass debe limitarse a esa invocación y hacerse únicamente después de la
verificación del SHA-256.

## 4. Clasificar la instalación; no adivinar

Ejecutar el diagnóstico de solo lectura. En una instalación antigua indicar la
carpeta y base reales:

```powershell
& "$Kit\extraido\release\Inspect-Station.ps1" `
  -LegacyRoot 'C:\ruta\modulo-pesaje' `
  -LegacyDatabasePath 'C:\ruta\modulo-pesaje\backend\instance\pesajes.db' `
  -OutputPath "$Kit\diagnostico-estacion.json"
```

La salida decide el carril:

| Resultado | Acción |
|---|---|
| `VERSIONED` | Seguir la sección 5. Nunca reimportar la base legacy. |
| `LEGACY` | Seguir la sección 6. |
| `PARTIAL_VERSIONED` | Detenerse. Respaldar y completar la instalación parcial; no reimportar. |
| `CONFLICT` | Detenerse. Hay dos bases candidatas y deben conciliarse. |
| `UNKNOWN` | Detenerse y localizar la instalación/base real. |

La existencia de un `.db` no basta: registrar también `-wal`, `-shm`, tamaño,
fecha y hash cuando el diagnóstico pueda calcularlo de forma consistente.

## 5. Carril A — estación ya versionada

Aplicar este carril únicamente cuando el diagnóstico diga `VERSIONED` y exista:

```text
C:\ProgramData\EnvaPeru\Pesaje\run\active-release.json
C:\ProgramData\EnvaPeru\Pesaje\data\pesajes.db
```

### 5.1 Configuración persistente

Revisar `C:\ProgramData\EnvaPeru\Pesaje\config\station.env`. Debe contener
valores reales, como mínimo:

```dotenv
STATION_CODE=PESAJE-PLANTA-01
STATION_UUID=<uuid-real-de-central>
STATION_MODE=MONITORED_LEGACY
SCM_OPERATOR_ID=<id-numerico-real>
CENTRAL_ORIGIN=https://envaperu-scm-api.onrender.com
ALLOW_INSECURE_CENTRAL=false
PORTFOLIO_DEMO_MODE=false
ALLOW_SCALE_SIMULATION=false
ALLOW_LOCAL_SCM_DEMO=false
SIMULATE_PRINTER=false
```

Conservar los valores físicos comprobados de `SCALE_PORT`,
`SCALE_BAUD_RATE`, `PRINTER_TYPE`, `PRINTER_NAME` y `PRINTER_PORT`. No guardar el
token en ese archivo.

Si falta el token, provisionarlo con el runtime activo y la cuenta operativa:

```powershell
$State = Get-Content 'C:\ProgramData\EnvaPeru\Pesaje\run\active-release.json' -Raw | ConvertFrom-Json
& "$($State.active_path)\backend\venv\Scripts\python.exe" `
  "$($State.active_path)\backend\station_control.py" `
  provision-token --data-root 'C:\ProgramData\EnvaPeru\Pesaje'
```

### 5.2 Detener y actualizar

Detener ordenadamente la estación actual y confirmar que el puerto 5050 quedó
libre. Ejecutar el **actualizador incluido en el paquete nuevo**, no una copia
antigua del launcher:

```powershell
& "$Kit\extraido\release\Update-Station.ps1" `
  -PackagePath $Zip `
  -ExpectedSha256 '<sha256-aprobado>'
```

El actualizador valida el paquete y cada archivo, repara un runtime parcial,
crea y verifica un backup SQLite, prueba las migraciones sobre una copia,
activa la versión, espera `READY`, valida identidad/configuración física y
espera un heartbeat aceptado por Central. Ante un fallo vuelve al release y
backup anteriores.

No usar `-NoStart` en la PC productiva.

## 6. Carril B — aplicación legacy no versionada

Usar únicamente cuando el diagnóstico diga `LEGACY`, no exista
`active-release.json`, el puerto 5050 esté libre y exista una sola base fuente.

El puente no copia el `.env` completo. Solo conserva parámetros físicos
permitidos y fuerza demo/simulaciones en `false`.

Para preparar el runtime offline busca Python 3.12 primero en los entornos
`backend\.venv` o `backend\venv` de la instalación legacy seleccionada y luego
en `PATH`/`py`. Si no encuentra exactamente Python 3.12 se detiene antes de
modificar la base; soporte debe instalar el runtime aprobado y repetir.

```powershell
& "$Kit\extraido\release\Migrate-LegacyStation.ps1" `
  -PackagePath $Zip `
  -ExpectedSha256 '<sha256-aprobado>' `
  -LegacyDatabasePath 'C:\ruta\modulo-pesaje\backend\instance\pesajes.db' `
  -LegacyEnvironmentPath 'C:\ruta\modulo-pesaje\.env' `
  -StationUuid '<uuid-real-de-central>' `
  -ScmOperatorId <id-numerico-real> `
  -StationCode 'PESAJE-PLANTA-01'
```

El puente ejecuta, en orden:

1. bloquea una estación activa, versionada, parcial o ambigua;
2. valida el ZIP/manifiesto sin activar un puntero;
3. crea y verifica el runtime desde los wheels offline;
4. genera `station.env` con una lista permitida;
5. solicita el token y lo cifra con DPAPI del usuario operativo;
6. respalda, migra y activa una copia consistente de la SQLite legacy;
7. exige fuente sin cambios, integridad `ok`, conteos e IDs conservados;
8. fija en la copia importada el UUID y código provisionados por Central;
9. ejecuta una única activación completa;
10. exige Central `ONLINE` y registra el launcher estable.

La base fuente legacy nunca se modifica. La evidencia queda en
`C:\ProgramData\EnvaPeru\Pesaje\backups`.

No usar `Update-Station.ps1 -NoStart` como puente: esa opción ya crea el puntero
activo y no representa una migración legacy.

Si un timeout de Central o el registro de la tarea falla **después** de la
primera activación, el actualizador detiene el proceso pero conserva el release,
la base importada y sus dos respaldos. Corregir la causa y reanudar exactamente
el mismo paquete; no volver a importar la SQLite legacy:

```powershell
& "$Kit\extraido\release\Update-Station.ps1" `
  -PackagePath $Zip `
  -ExpectedSha256 '<sha256-aprobado>' `
  -ResumeFirstActivation
```

`-ResumeFirstActivation` solo acepta una primera activación sin release anterior,
con la misma versión/ruta y ambos respaldos registrados. No permite reemplazar
un release activo normal con el mismo número de versión.

## 7. Smoke físico obligatorio

```powershell
$Ready = Invoke-RestMethod 'http://127.0.0.1:5050/api/local/v1/health/ready'
$Ready | ConvertTo-Json -Depth 8
Get-Content 'C:\ProgramData\EnvaPeru\Pesaje\run\active-release.json'
```

Confirmar en presencia de operación:

1. `status=READY` y `central.state=ONLINE`;
2. UUID/código de estación y operador correctos;
3. pestaña **Legacy temporal** con historial anterior;
4. pestañas **Nuevo · SCM** para Etiquetas y Pesaje SCM;
5. balanza real estable y sin captura manual;
6. una preetiqueta controlada imprime dos stickers idénticos;
7. lectura del QR mediante escáner, que equivale a texto + Enter;
8. peso y acuse visibles en Central;
9. una reimpresión controlada respeta el ledger y no duplica una emisión incierta;
10. tarea `EnvaPeru Pesaje Edge` inicia con la cuenta operativa y supera un reinicio.

La primera etiqueta es una prueba controlada, no producción. Solo después de
firmar el smoke se autoriza el corte.

## 8. Rollback

### Actualización versionada

Solo si no hubo capturas, impresiones, stickers físicos, acuses ni movimientos
nuevos:

```powershell
cd 'C:\Program Files\EnvaPeru\Pesaje\launcher'
.\Rollback-Station.ps1 -ConfirmNoCapturesSinceUpdate
```

El script espera que el proceso y puerto terminen antes de restaurar SQLite y
luego inicia la versión anterior.

### Primera conversión legacy

No existe un release versionado anterior. Antes de producir, detener la versión
nueva y volver manualmente a la aplicación legacy con su SQLite fuente intacta.
Conservar `ProgramData` y todos los backups como evidencia.

Después de cualquier hecho productivo nuevo, no restaurar una base anterior:
detener la operación, conciliar y recuperar hacia adelante.

## Evidencia mínima del acta

- clasificación y `diagnostico-estacion.json`;
- usuario Windows operativo;
- versión/commit anterior y nueva;
- SHA-256 del paquete;
- ruta/hash/conteos/IDs de la fuente y backup;
- UUID, código y operador (nunca el token);
- salida de activación y `/ready`;
- resultados de balanza, doble sticker, QR, Central y reinicio;
- hora de autorización o de rollback.
