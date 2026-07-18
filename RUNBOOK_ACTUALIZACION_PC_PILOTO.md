# Runbook de actualizacion de la PC piloto

Este procedimiento migra la base SQLite legacy al almacenamiento release sin usar `copy`, `xcopy` ni el Explorador de Windows. La base original se mantiene en su ruta y el importador trabaja desde una fotografia consistente creada por SQLite.

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
git pull
.\install-windows.bat
```

El instalador nuevo solo prepara dependencias y compila el frontend. No ejecuta `create_app`, `init_db.py` ni otra inicializacion sobre la base legacy.

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

## 4. Smoke test release

```powershell
.\start-windows.bat
```

En otra consola:

```powershell
Invoke-RestMethod http://127.0.0.1:5050/api/local/v1/health/live
Invoke-RestMethod http://127.0.0.1:5050/api/local/v1/health/ready
```

Confirmar `LIVE`, `READY`, historial visible, balanza conectada y una impresion de prueba controlada. No habilitar pesaje productivo hasta cerrar esta validacion.

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

