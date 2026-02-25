@echo off
echo Iniciando Scale Module (Backend + Frontend)...

:: 1. Ir a la carpeta del proyecto
cd /d "%~dp0"

:: 2. Iniciar Backend en una nueva ventana CMD
echo Levantando Backend (Python/Flask)...
start "Scale Module - BACKEND" cmd /k "cd backend && venv\Scripts\activate && python run.py"

:: 3. Esperar un par de segundos para que el backend despierte
timeout /t 3 /nobreak > NUL

:: 4. Iniciar Frontend Vite (esto abrirá el navegador automáticamente)
echo Levantando Frontend (React/Vite)...
cd frontend
npm run dev
