# ENVAPERU Scale Module Desktop

Aplicación de escritorio para gestión de pesajes con balanza y generación de stickers.

## Arquitectura

```
├── backend/          # API Flask (Python)
├── frontend/         # UI React; Vite solo compila el artefacto
└── electron/         # Wrapper legado, fuera del perfil piloto
```

## Requisitos

- Python 3.12
- Node.js 18+ solo para instalar y compilar el frontend
- Windows con acceso a los puertos COM y a la impresora
- SQLite incluido para la persistencia local del piloto

## Setup - Desarrollo

### 1. Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Crear base de datos
# En PostgreSQL: CREATE DATABASE scale_module;

# Copiar y configurar variables de entorno
copy ..\.env.example .env

# Ejecutar
python run.py
```

Para desarrollo guiado por pruebas, instalar las dependencias separadas y ejecutar la suite aislada:

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

Las pruebas fuerzan SQLite en memoria y desactivan la sincronización en background. No abren la balanza ni la impresora. Desde la raíz del workspace maestro se recomienda usar `.\scripts\test.ps1 -Component pesaje`.

El contrato consumidor con backend central se valida mediante:

```powershell
python -m pytest tests/test_sync_contract.py
```

### 2. Frontend

```powershell
cd frontend
npm install
npm run dev
```

### 3. Electron (opcional para desarrollo)

```powershell
cd electron
npm install
npm run dev
```

## Perfil Release - Piloto Windows

El piloto usa Python 3.12, Waitress y el frontend React compilado. Electron y PyInstaller no forman parte de este perfil.

### 1. Compilar Frontend

```powershell
cd frontend
npm run build
# Genera: frontend/dist/
```

### 2. Iniciar Estación

```powershell
cd ..
.\start-windows.bat
```

`start-windows.bat` ejecuta `backend/station_main.py`: Waitress escucha solo en `127.0.0.1:5050`, sirve UI/API/Socket.IO desde el mismo origen, desactiva debug, reloader y sincronización legacy, y rechaza una segunda instancia de la misma estación.

Health local:

- `GET /api/local/v1/health/live`
- `GET /api/local/v1/health/ready`

Parada ordenada para el operador:

```powershell
.\stop-windows.bat
```

Para automatización también está disponible `station-control.ps1 stop`. Ambos señalizan el evento local de la estación; no usan `taskkill` ni exponen una ruta HTTP de apagado.

`run.py` y `start-dev.bat` se conservan exclusivamente para desarrollo.

### Persistencia y recuperacion

El perfil release guarda los datos fuera del codigo. Sin configuracion adicional usa:

```text
C:\ProgramData\EnvaPeru\Pesaje\config\
C:\ProgramData\EnvaPeru\Pesaje\secrets\
C:\ProgramData\EnvaPeru\Pesaje\data\pesajes.db
C:\ProgramData\EnvaPeru\Pesaje\backups\
C:\ProgramData\EnvaPeru\Pesaje\logs\
C:\ProgramData\EnvaPeru\Pesaje\run\
```

En el primer arranque se comprueba el historial `schema_migrations`. Una base existente se respalda y valida antes de aplicar migraciones; una base con version mayor que el binario impide iniciar la captura. SQLite se abre con claves foraneas, WAL, sincronizacion `FULL` y espera de bloqueo de 5 segundos.

Crear el backup diario o uno manual:

```powershell
.\backup-windows.bat
backend\venv\Scripts\python.exe backend\station_storage.py backup --reason manual
```

Verificar un backup sin restaurarlo:

```powershell
backend\venv\Scripts\python.exe backend\station_storage.py verify "C:\ProgramData\EnvaPeru\Pesaje\backups\pesajes_....db"
```

Restaurar exige detener primero la estacion. El comando valida manifiesto, SHA-256, identidad de estacion, integridad, conteos y maximos IDs sobre una copia temporal. La base reemplazada se conserva como `incident-*.db`.

```powershell
.\stop-windows.bat
backend\venv\Scripts\python.exe backend\station_storage.py restore "C:\ProgramData\EnvaPeru\Pesaje\backups\pesajes_....db"
.\start-windows.bat
```

#### Importar la base legacy de la PC piloto

El procedimiento operativo completo esta en [RUNBOOK_ACTUALIZACION_PC_PILOTO.md](RUNBOOK_ACTUALIZACION_PC_PILOTO.md).

No usar `copy`, `xcopy`, el Explorador de Windows ni sincronizacion de nube para mover la base mientras el backend antiguo este abierto. SQLite puede tener transacciones vigentes en los archivos `-wal` y `-shm`; copiar solo `pesajes.db` en ese estado puede producir una fotografia incompleta.

El importador abre el origen en modo lectura, crea una fotografia consistente con la API de backup de SQLite, valida `integrity_check`, SHA-256, conteos e IDs maximos, migra una copia temporal y activa el resultado con reemplazo atomico. El archivo legacy original no se renombra, no se elimina y no se escribe.

1. Cerrar el backend antiguo con `Ctrl+C` o cerrando su CMD y confirmar que ya no existe un listener en el puerto `5050`.
2. Identificar la base activa. Con la configuracion legacy por defecto suele ser `backend\instance\pesajes.db`.
3. Ejecutar desde la raiz del modulo:

```powershell
.\import-legacy-windows.bat ".\backend\instance\pesajes.db"
```

El exito se confirma unicamente cuando la salida JSON termina con `"event": "LEGACY_IMPORT_COMPLETE"`, `"source_unchanged": true` e `"integrity_check": "ok"`. Los respaldos y manifiestos quedan en `C:\ProgramData\EnvaPeru\Pesaje\backups\`.

Si ya existe una base destino con pesajes, el comando se detiene sin reemplazarla. Solo despues de comparar ambas bases y aprobar expresamente el reemplazo se permite:

```powershell
.\import-legacy-windows.bat ".\backend\instance\pesajes.db" --replace-existing
```

Despues del exito se inicia el release con `.\start-windows.bat`. Si el release no supera el smoke test, se detiene y se vuelve a operar temporalmente con el runtime legacy y su archivo original intacto; nunca deben ejecutarse ambos backends a la vez.

`--data-root` permite aislar datos en desarrollo. `--database-path` se mantiene como override de compatibilidad y para migrar una copia legacy controlada; una instalacion nueva no debe guardar SQLite dentro del release.

### Captura idempotente e impresion

El flujo release genera un UUID `capture_id` antes de aceptar F2 y conserva el mismo identificador y payload hasta obtener una respuesta concluyente. Esto permite reintentar una respuesta perdida sin crear otro pesaje:

- primera solicitud: `201` y un nuevo registro;
- misma clave y mismo payload: `200` y el registro original;
- misma clave con otro payload: `409 IDEMPOTENCY_CONFLICT`.

Guardar e imprimir son resultados independientes. Una falla de impresora conserva el pesaje y registra cada intento como `PENDING`, `SUCCEEDED` o `FAILED`; el operador reintenta la etiqueta sobre el mismo `capture_id`, sin repetir F2.

Estados visibles:

- `SAVED_PRINTED`;
- `SAVED_PRINT_PENDING`;
- `SAVED_PRINT_FAILED`.

### Correcciones trazables en release

Un pesaje confirmado no se edita ni se elimina desde la estación. La UI permite
registrar una **solicitud de corrección** append-only sobre el registro original:

- `CORRECT` propone nuevos valores sin aplicarlos al pesaje;
- `VOID` solicita anular el efecto futuro del pesaje, pero no lo borra;
- `requested_by` y `reason` son obligatorios;
- `evidence_reference` es opcional;
- se conservan el snapshot original, los cambios propuestos, la clasificación de
  trazabilidad y la fecha UTC de la solicitud.

Una solicitud local no corrige inventario central ni confirma que el ajuste fue
aprobado. Hasta que US-010D defina la adjudicación central:

- un pesaje local queda en `PENDING_LOCAL_REVIEW`;
- un pesaje `LEGACY_ACKNOWLEDGED_UNVERIFIABLE` queda en
  `REQUIRES_CENTRAL_REVIEW`.

La solicitud también es idempotente mediante `Idempotency-Key` UUID: la primera
creación devuelve `201`, el replay exacto devuelve `200` y reutilizar la clave
con otro payload devuelve `409 IDEMPOTENCY_CONFLICT`.

En `RELEASE`, crear por el endpoint legacy devuelve
`403 LEGACY_CAPTURE_DISABLED`; editar, eliminar o hacer bulk delete devuelve
`403 DESTRUCTIVE_MUTATION_DISABLED`. Cambiar manualmente `sincronizado` devuelve
`403 MANUAL_SYNC_DISABLED`. `LEGACY_MIGRATION_MODE=True` existe solo para una
migración controlada, nunca para la operación diaria.

## Configuración

Editar `.env` con los puertos de la balanza e impresora:

| Variable | Descripción | Default |
|----------|-------------|---------|
| `SCALE_PORT` | Puerto COM de la balanza | COM4 |
| `SCALE_BAUD_RATE` | Baudios de comunicación | 9600 |
| `PRINTER_PORT` | Puerto de la impresora | COM3 |
| `PRINTER_TYPE` | Tipo: ESC_POS o ZPL | ESC_POS |
| `DATABASE_URL` | SQLite de desarrollo; release usa ProgramData | `sqlite:///pesajes.db` |
| `STATION_DATA_ROOT` | Override del directorio persistente | ProgramData |
| `BACKUP_RETENTION_COUNT` | Numero de backups validos conservados | 14 |
| `MAX_CAPTURE_WEIGHT_KG` | Maximo tecnico aceptado por captura local | 1000 |
| `LEGACY_MIGRATION_MODE` | Habilita mutaciones legacy solo durante una migración controlada | False |
| `LOG_FILE_LEVEL` | Nivel mínimo del archivo compartido de estación | INFO |
| `LOG_CONSOLE_LEVEL` | Nivel mínimo visible en CMD | INFO |
| `LOG_MAX_BYTES` | Tamaño antes de rotar el log | 10485760 |
| `LOG_BACKUP_COUNT` | Archivos rotados conservados | 10 |
| `LOG_ROTATION_RETRY_SECONDS` | Espera si Windows bloquea el renombrado | 300 |

En release todos los componentes escriben mediante un único handler en
`C:\ProgramData\EnvaPeru\Pesaje\logs\scale_module.log`. Las muestras continuas
de la balanza se registran en `DEBUG`; `INFO` queda reservado para cambios de
estado y operaciones relevantes.

## API Endpoints

### Balanza
- `GET /api/balanza/status` - Estado de conexión
- `POST /api/balanza/conectar` - Conectar
- `POST /api/balanza/iniciar-escucha` - Iniciar escucha continua
- `GET /api/balanza/ultimo-peso` - Último peso capturado

### Pesajes
- `GET /api/pesajes` - Listar pesajes
- `POST /api/local/v1/pesajes` - Crear o recuperar una captura con `Idempotency-Key`
- `POST /api/local/v1/pesajes/:capture_id/print` - Registrar un intento de impresion sobre la captura
- `POST /api/local/v1/pesajes/:id/corrections` - Crear o recuperar una solicitud de corrección con `Idempotency-Key`
- `GET /api/local/v1/pesajes/:id/corrections` - Consultar el historial append-only de solicitudes
- `POST /api/pesajes` - Endpoint legacy bloqueado en release
- `PUT|DELETE /api/pesajes/:id` - Mutaciones legacy bloqueadas en release
- `POST /api/pesajes/bulk-delete` - Eliminación masiva bloqueada en release
- `POST /api/pesajes/marcar-sincronizado` - Cambio manual bloqueado fuera de testing/migración
- `POST /api/pesajes/:id/imprimir` - Reimpresion compatible con intento durable

## Monitoreo Central Offline-first

La estacion conserva una identidad UUID en SQLite y reporta un heartbeat de
estado al backend central. La comunicacion sirve para monitoreo; no crea
`ControlPeso`, no mueve inventario y no habilita comandos remotos de hardware.

Flujo de provisionamiento:

1. Iniciar la estacion una vez y consultar su identidad:

```powershell
backend\.venv\Scripts\python.exe backend\station_control.py identity
```

2. En el backend central, crear las tablas y registrar esa misma identidad:

```powershell
python scripts\migrate_station_monitoring.py
flask --app run.py provision-weighing-station `
  --station-id <UUID> `
  --code PESAJE-PLANTA-01 `
  --name "Balanza principal" `
  --location "Planta - pesaje"
```

3. Introducir en la estacion el valor `TOKEN_ONCE` mostrado por central:

```powershell
backend\.venv\Scripts\python.exe backend\station_control.py provision-token
```

El comando usa entrada oculta y guarda el secreto cifrado con Windows DPAPI en
`ProgramData\EnvaPeru\Pesaje\secrets`. El token no se escribe en `.env`, logs,
heartbeat ni UI. Con `--data-root` se puede provisionar una instalacion aislada.

Variables nuevas: `STATION_CODE`, `STATION_MODE`, `STATION_APP_VERSION`,
`CENTRAL_ORIGIN`, `ALLOW_INSECURE_CENTRAL`, `MONITORING_ENABLED` y
`HEARTBEAT_SECONDS`. `CENTRAL_ORIGIN` es un origen sin `/api`, credenciales,
query ni fragmento. HTTP se admite automaticamente solo para loopback; un host
remoto exige HTTPS o `ALLOW_INSECURE_CENTRAL=true` como excepcion consciente de
una LAN controlada. `SYNC_ENABLED=false` mantiene separada y deshabilitada la
sincronizacion legacy.

Estados visibles del enlace central:

- `ONLINE`: capabilities y ultimo heartbeat fueron aceptados;
- `CENTRAL_NOT_PROVISIONED`: falta el token; no se hacen llamadas anonimas;
- `CENTRAL_UNREACHABLE`: central no responde; la captura local sigue disponible;
- `CENTRAL_CONFIG_ERROR`: el origen central no cumple la politica de seguridad;
- `AUTH_ERROR` o `CENTRAL_INCOMPATIBLE`: requiere soporte o actualizacion.

`GET /api/local/v1/health/ready` incluye el bloque `central`, pero una caida de
central no devuelve `503` mientras la base local permita capturar con seguridad.

### Importacion historica legacy

La migracion del historial se realiza desde una copia estatica de SQLite, nunca
desde el archivo activo que usa la balanza. Primero se inspecciona sin transmitir
datos:

```powershell
backend\.venv\Scripts\python.exe backend\station_history.py inspect `
  C:\ruta\pesajes-copy.db --station-id <UUID>
```

El comando muestra SHA-256, conteos, rango temporal e identificador determinista
de importacion. La publicacion requiere el token DPAPI ya provisionado, que la
API anuncie `station-legacy-history-v1` y una confirmacion explicita:

```powershell
backend\.venv\Scripts\python.exe backend\station_history.py publish `
  C:\ruta\pesajes-copy.db --station-id <UUID> `
  --central-origin https://central.example `
  --confirm-static-backup
```

Repetir el mismo comando es idempotente. Las OP, colores, eliminaciones y cierres
se conservan como evidencia literal; esta carga no crea `ControlPeso` ni mueve
inventario SCM.
