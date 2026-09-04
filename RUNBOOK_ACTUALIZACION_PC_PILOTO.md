# Runbook de instalación y actualización de la PC piloto

La primera instalación migra la base SQLite legacy al almacenamiento release. Las actualizaciones siguientes ya no se realizan mediante `git pull`: usan un paquete inmutable generado por CI, backup previo, preflight sobre una copia, activación por puntero y rollback automático.

## Dos procedimientos distintos

1. **Primera instalación:** seguir las secciones 1 a 5 para preservar la SQLite legacy e inicializar `ProgramData`.
2. **Actualización de una estación ya versionada:** seguir la sección 6. No volver a importar la SQLite legacy.

## Condiciones de inicio

- No hay un pesaje en curso ni una etiqueta pendiente.
- El CMD del backend legacy esta cerrado.
- El puerto local `5050` ya no esta en escucha.
- Se conoce la ruta exacta de la base usada por el backend legacy.
- El estado Git del codigo fue revisado antes del pull.
- Hay una ventana operativa para smoke test sin produccion real.

No continuar si alguna condicion no se cumple.

## 1. Registrar el estado anterior

Desde PowerShell, en la raiz de `modulo-pesaje`:

```powershell
git status --short
git rev-parse HEAD
Get-NetTCPConnection -LocalPort 5050 -State Listen -ErrorAction SilentlyContinue
Resolve-Path ".\backend\instance\pesajes.db"
Get-Item ".\backend\instance\pesajes.db" | Select-Object FullName, Length, LastWriteTime
Get-FileHash ".\backend\instance\pesajes.db" -Algorithm SHA256
```

`Get-NetTCPConnection` no debe devolver ningun listener. Guardar el commit, tamano y SHA-256 en el acta de despliegue. Si `DATABASE_URL` fue personalizado, usar su ruta real en vez del ejemplo.

## 2. Actualizar sin abrir la base

```powershell
git fetch origin
git switch codex/monitored-offline-pilot
git pull --ff-only origin codex/monitored-offline-pilot
.\install-windows.bat
```

El instalador nuevo solo prepara dependencias y compila el frontend. No ejecuta `create_app`, `init_db.py` ni otra inicializacion sobre la base legacy.

Antes del primer arranque, crear o actualizar `.env` en la raiz del modulo con la identidad ya registrada en la API central:

```dotenv
STATION_CODE=PESAJE-PLANTA-01
STATION_UUID=6e4a5f65-67b7-413d-a780-1c9a2669e50f
STATION_MODE=MONITORED_LEGACY
STATION_APP_VERSION=1.1.0-pilot
CENTRAL_ORIGIN=https://envaperu-scm-api.onrender.com
ALLOW_INSECURE_CENTRAL=false
MONITORING_ENABLED=true
SYNC_ENABLED=false
TIMEZONE=America/Lima
```

`STATION_UUID` debe coincidir con la estacion usada para importar el historico. No iniciar el modulo con otro UUID: eso crearia una segunda identidad y separaria los pesajes nuevos de los 11 676 registros importados.

## 3. Ejecutar la importacion segura

```powershell
.\import-legacy-windows.bat ".\backend\instance\pesajes.db"
```

El wrapper vuelve a bloquear la operacion si detecta el puerto `5050`. El comando interno realiza, en orden:

1. inspeccion de integridad del origen en modo lectura;
2. SHA-256, conteos e IDs maximos del origen;
3. backup consistente SQLite con manifiesto `VALID`;
4. migraciones versionadas sobre una copia temporal;
5. nueva comprobacion de integridad y metricas;
6. backup verificado de cualquier destino previo;
7. activacion atomica en `C:\ProgramData\EnvaPeru\Pesaje\data\pesajes.db`.

No continuar salvo que la ultima salida JSON contenga:

```text
"event": "LEGACY_IMPORT_COMPLETE"
"source_unchanged": true
"integrity_check": "ok"
```

Comparar `source.sha256`, `table_counts.pesajes` y `max_ids.pesajes` con la evidencia previa. Registrar tambien `source_backup.path`, `source_backup.manifest_path` e `incident_path` cuando exista.

Si el destino ya contiene pesajes, el importador devuelve `STORAGE_ERROR` y no lo reemplaza. `--replace-existing` solo se usa despues de comparar ambas bases y dejar aprobacion explicita:

```powershell
.\import-legacy-windows.bat ".\backend\instance\pesajes.db" --replace-existing
```

Provisionar en esta PC el token de esa misma estacion. El valor se introduce de forma oculta y queda cifrado con DPAPI; no se guarda en `.env`:

```powershell
backend\venv\Scripts\python.exe backend\station_control.py provision-token
```

## 4. Smoke test release

```powershell
.\start-windows.bat
```

En otra consola:

```powershell
Invoke-RestMethod http://127.0.0.1:5050/api/local/v1/health/live
Invoke-RestMethod http://127.0.0.1:5050/api/local/v1/health/ready
backend\venv\Scripts\python.exe backend\station_control.py identity
```

Confirmar `LIVE`, `READY`, identidad `6e4a5f65-67b7-413d-a780-1c9a2669e50f`, enlace central `ONLINE`, historial visible, balanza conectada y una impresion de prueba controlada. No habilitar pesaje productivo hasta cerrar esta validacion.

## 5. Rollback antes de producir

Si falla el smoke test:

```powershell
.\stop-windows.bat
Get-NetTCPConnection -LocalPort 5050 -State Listen -ErrorAction SilentlyContinue
```

La base legacy original sigue intacta y puede volver a usarse con el commit anterior registrado. No eliminar ProgramData ni los backups: se conservan como evidencia para diagnostico.

El rollback directo solo es valido antes de capturar produccion en el release. Si el release ya registro pesajes reales, volver al archivo legacy produciria dos historiales divergentes y exige conciliacion antes de reanudar.

## Codigos relevantes

| Codigo | Significado | Accion |
|---:|---|---|
| `0` | Importacion completa | Revisar evidencia y ejecutar smoke test |
| `2` | Argumento o entorno Python invalido | Corregir ruta/instalacion; no hubo activacion |
| `6` | Estacion o puerto activo | Detener backend y repetir |
| `7` | Error de almacenamiento o validacion | No iniciar; revisar detalle JSON y backups |

## 6. Actualizaciones versionadas posteriores

### 6.1. Preparar la ventana

- terminar o cancelar la sesión de pesaje activa;
- confirmar que no existe una etiqueta pendiente de impresión;
- descargar desde el artefacto privado de CI el ZIP y su `.sha256`;
- obtener el SHA-256 también por el canal de soporte y compararlo;
- no copiar repositorios, `node_modules`, `.env`, bases SQLite ni tokens dentro del paquete.

### 6.2. Ejecutar la actualización

Abrir PowerShell como administrador:

```powershell
cd C:\Program Files\EnvaPeru\Pesaje\launcher
.\Update-Station.ps1 `
  -PackagePath C:\Soporte\envaperu-pesaje-1.2.0-win-x64.zip `
  -ExpectedSha256 <sha256-aprobado>
```

El actualizador ejecuta en orden:

1. valida el hash integral del ZIP;
2. extrae en staging y valida `manifest.json` y todos sus archivos;
3. crea un venv nuevo desde `wheels`, sin Internet;
4. crea y verifica un backup SQLite;
5. prueba las migraciones sobre una copia;
6. detiene ordenadamente el release activo;
7. cambia `active-release.json`;
8. inicia la versión nueva y espera `READY`;
9. si falla, recupera puntero, SQLite y runtime anteriores.

No continuar si la salida no termina en:

```text
UPDATE_COMPLETE version=<version> backup=<ruta>
```

### 6.3. Smoke posterior

```powershell
Invoke-RestMethod http://127.0.0.1:5050/api/local/v1/health/live
Invoke-RestMethod http://127.0.0.1:5050/api/local/v1/health/ready
Get-Content C:\ProgramData\EnvaPeru\Pesaje\run\active-release.json
```

Confirmar versión, `READY`, balanza, impresora, Central y el historial de la sesión. La primera etiqueta del release se imprime como prueba controlada, no como producción.

En la primera instalación versionada, registrar una vez el arranque estable:

```powershell
C:\Program Files\EnvaPeru\Pesaje\launcher\Install-StationTask.ps1
```

La tarea se vincula al launcher, no a una carpeta de versión. Probarla cerrando la estación, ejecutando manualmente la tarea y finalmente reiniciando Windows dentro de la ventana UAT.

### 6.4. Rollback

El rollback por fallo de readiness es automático. Para un rollback manual sin capturas posteriores:

```powershell
.\release\Rollback-Station.ps1 -ConfirmNoCapturesSinceUpdate
```

Si ya hubo capturas o impresiones, detener y escalar: no restaurar una base anterior hasta conciliar los hechos nuevos.
