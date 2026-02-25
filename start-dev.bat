@echo off
echo Iniciando Scale Module - Entorno Local (Windows)
echo =================================================

:: Abrir Backend en nueva ventana silenciosamente
echo [1/2] Levantando Backend (Flask)...
start "Scale Module - Backend" cmd /c "cd backend && venv\Scripts\activate.bat && python run.py"

:: Abrir Frontend en esta misma ventana
echo [2/2] Levantando Frontend (Vite)...
cd frontend
npm run dev

:: Al cerrar la ventana del frontend no cierra la del backend solita con start, 
:: pero es lo estándar en .bat de Windows.
pause
