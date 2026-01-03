# ENVAPERU Scale Module Desktop

Aplicación de escritorio para gestión de pesajes con balanza y generación de stickers.

## Arquitectura

```
├── backend/          # API Flask (Python)
├── frontend/         # UI React (Vite)
└── electron/         # Wrapper Electron
```

## Requisitos

- Python 3.10+
- Node.js 18+
- PostgreSQL

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

## Build - Producción

### 1. Build Backend (PyInstaller)

```powershell
cd backend
pyinstaller scale_module.spec
# Genera: backend/dist/scale_module_backend.exe
```

### 2. Build Frontend

```powershell
cd frontend
npm run build
# Genera: frontend/dist/
```

### 3. Build Electron

```powershell
cd electron
npm run build
# Genera: release/ENVAPERU Balanza Setup.exe
```

## Configuración

Editar `.env` con los puertos de la balanza e impresora:

| Variable | Descripción | Default |
|----------|-------------|---------|
| `SCALE_PORT` | Puerto COM de la balanza | COM4 |
| `SCALE_BAUD_RATE` | Baudios de comunicación | 9600 |
| `PRINTER_PORT` | Puerto de la impresora | COM3 |
| `PRINTER_TYPE` | Tipo: ESC_POS o ZPL | ESC_POS |
| `DATABASE_URL` | Conexión PostgreSQL | localhost |

## API Endpoints

### Balanza
- `GET /api/balanza/status` - Estado de conexión
- `POST /api/balanza/conectar` - Conectar
- `POST /api/balanza/iniciar-escucha` - Iniciar escucha continua
- `GET /api/balanza/ultimo-peso` - Último peso capturado

### Pesajes
- `GET /api/pesajes` - Listar pesajes
- `POST /api/pesajes` - Crear pesaje
- `POST /api/pesajes/:id/imprimir` - Imprimir sticker
