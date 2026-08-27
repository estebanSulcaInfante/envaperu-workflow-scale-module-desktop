# Releases versionados de la estación de pesaje

Este directorio implementa el carril de actualización del módulo edge. El código se instala en versiones paralelas y la información de planta permanece fuera del release.

## Contrato operativo

- Código inmutable: `C:\Program Files\EnvaPeru\Pesaje\releases\{version}`.
- Datos, token DPAPI, configuración, logs y backups: `C:\ProgramData\EnvaPeru\Pesaje`.
- Puntero activo: `ProgramData\run\active-release.json`.
- Una actualización nunca elimina un release previo.
- Antes de activar se verifica el SHA-256 del ZIP, cada archivo del manifiesto, un backup SQLite y una migración sobre una copia.
- La estación se detiene solo después del preflight. Si el nuevo runtime no llega a `READY`, se restaura el puntero, la base previa y el runtime anterior.
- No se actualiza durante un pesaje, una impresión pendiente ni una sesión operativa activa.

El SHA-256 prueba integridad. Para el piloto, la autoridad del paquete proviene del artefacto privado generado por CI y del valor comunicado por soporte por un canal separado. La firma de código Authenticode queda como gate antes de distribuir releases fuera de ese canal controlado.

## Crear un paquete

```powershell
.\release\Build-StationRelease.ps1 -Version 1.2.0
```

El constructor se detiene si Git no está disponible o si el árbol contiene
cambios sin confirmar, incluidos archivos nuevos. Así, `source_revision` siempre
identifica exactamente los insumos del paquete; no existe un escape para generar
un release desde un árbol sucio. El resultado contiene el ZIP y su `.sha256`. El
frontend ya está compilado y el directorio `wheels` permite instalar Python sin
Internet ni Node.js en la PC de planta. Si el ZIP o su sidecar ya existen, el
constructor aborta: una versión publicada nunca se sobrescribe; se incrementa
la versión.

## Actualizar una estación

Ejecutar PowerShell como administrador, fuera del horario de pesaje:

Antes de detener nada, generar un diagnóstico sin exponer secretos. En una
instalación legacy indicar también la carpeta antigua y, si no usa la ruta
predeterminada, la base exacta:

```powershell
.\release\Inspect-Station.ps1 `
  -LegacyRoot C:\EnvaPeru\modulo-pesaje `
  -LegacyDatabasePath C:\EnvaPeru\modulo-pesaje\backend\instance\pesajes.db `
  -OutputPath C:\Soporte\diagnostico-estacion.json
```

El resultado distingue `LEGACY`, `VERSIONED`, `PARTIAL_VERSIONED`, `CONFLICT` o
`UNKNOWN`, registra el release, el puerto y los archivos SQLite/WAL, y solo
incluye valores operativos permitidos. Nunca lee ni muestra el token central o
`SECRET_KEY`. Ante `PARTIAL_VERSIONED` o `CONFLICT` se detiene el procedimiento:
nunca se elige automáticamente entre dos SQLite.

Si el resultado es `LEGACY`, no ejecutar el actualizador directamente. Usar el
puente desde el paquete extraído, pasando UUID e ID de operador reales:

```powershell
.\release\Migrate-LegacyStation.ps1 `
  -PackagePath C:\Soporte\envaperu-pesaje-1.2.0-pilot.3-win-x64.zip `
  -ExpectedSha256 <sha256-comunicado-por-soporte> `
  -LegacyDatabasePath C:\EnvaPeru\modulo-pesaje\backend\instance\pesajes.db `
  -LegacyEnvironmentPath C:\EnvaPeru\modulo-pesaje\.env `
  -StationUuid <uuid-real-de-central> `
  -ScmOperatorId 123
```

El puente hace stage sin activación, instala el runtime offline, importa y
verifica la base legacy, genera configuración física sin modos simulados,
provisiona el token con DPAPI, fija el UUID/código de Central en la copia
importada y recién entonces realiza una activación completa.
Puede reutilizar un Python 3.12 de `backend\.venv` o `backend\venv` de la
instalación seleccionada cuando no está publicado en `PATH`. La cuenta que
ejecuta el puente debe ser la misma de la tarea programada.

Antes de la primera activación SCM, completar
`C:\ProgramData\EnvaPeru\Pesaje\config\station.env`:

```dotenv
CENTRAL_ORIGIN=https://envaperu-scm-api.onrender.com
ALLOW_INSECURE_CENTRAL=false
SCM_OPERATOR_ID=123
```

`SCM_OPERATOR_ID` es el ID numérico positivo del trabajador autorizado para
el piloto; no es un nombre ni un valor ficticio. Provisionar además el token
de la misma estación, sin guardarlo en `station.env`:

```powershell
& 'C:\Program Files\EnvaPeru\Pesaje\releases\<version>\backend\venv\Scripts\python.exe' `
  'C:\Program Files\EnvaPeru\Pesaje\releases\<version>\backend\station_control.py' `
  provision-token --data-root C:\ProgramData\EnvaPeru\Pesaje
```

```powershell
.\release\Update-Station.ps1 `
  -PackagePath C:\Soporte\envaperu-pesaje-1.2.0-win-x64.zip `
  -ExpectedSha256 <sha256-comunicado-por-soporte>
```

El actualizador valida identidad, origen central, token DPAPI, modos físicos y
`SCM_OPERATOR_ID` antes de activar; después exige `READY` y un heartbeat
aceptado en el arranque actual. Solo `PILOT_CONFIG_READY`, `CENTRAL_ONLINE` y
`UPDATE_COMPLETE` acreditan una actualización operativa. Si falta algún dato,
la actualización falla y aplica rollback; `UPDATE_STAGED` solo se usa en pruebas
o cuando soporte difiere conscientemente el arranque.

Una primera conversión legacy no tiene release versionado anterior. Si falla
después de crear el puntero, se conserva detenida y puede retomarse sin reimportar
la fuente ejecutando el mismo actualizador/paquete con
`-ResumeFirstActivation`. El modo resume exige los backups original y
posmigración registrados, y no habilita reactivar versiones normales.

## Incidente de impresión

- `FALLIDA_SIN_EMISION`: el spooler no aceptó bytes; el retry normal es seguro.
- `IMPRESA` con acuse pendiente: usar **Reanudar acuse central**; esta acción no
  vuelve a imprimir.
- `EMISION_INCIERTA` o `PARCIAL`: no usar un retry genérico. Separar el material,
  conciliar el sticker y tramitar un reemplazo supervisado con motivo y auditoría
  en Central. Esta versión de la estación no incluye un override local.

Después de la primera instalación versionada, registrar una vez el launcher estable al iniciar sesión:

```powershell
C:\Program Files\EnvaPeru\Pesaje\launcher\Install-StationTask.ps1
```

La tarea no apunta a una versión concreta. En cada inicio lee `active-release.json`, evita una segunda instancia y permite que la versión cambie sin editar accesos directos.

## Rollback manual

El actualizador ya hace rollback automático si falla readiness. El rollback manual exige confirmar que no hubo nuevas capturas desde la actualización:

```powershell
.\release\Rollback-Station.ps1 -ConfirmNoCapturesSinceUpdate
```

Si hubo pesajes, impresiones o movimientos nuevos, no se ejecuta rollback ciego: se detiene la operación y se concilian primero los registros.

## Qué no hace

- no descarga ni instala una versión silenciosamente;
- no permite a Central abrir la balanza, imprimir o detener la estación;
- no borra datos de `ProgramData`;
- no sustituye el smoke físico de balanza e impresora;
- no firma todavía el paquete con un certificado Authenticode.
