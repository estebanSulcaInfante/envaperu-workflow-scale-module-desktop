@echo off
setlocal
echo ====================================================
echo   INSTALADOR AUTOMATICO - SCALE MODULE ENVAPERU
echo ====================================================
echo.

:: 1. Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no esta instalado o no fue agregado al PATH.
    echo Por favor instala Python 3.12+ y marca 'Add Python to PATH'.
    pause
    exit /b
)

:: 2. Verificar Node.js
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js no esta instalado.
    echo Por favor instala Node.js (LTS) desde nodejs.org.
    pause
    exit /b
)

:: 3. Preparar Backend
echo.
echo [1/3] Preparando Entorno Python (Backend)...
cd backend
if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate
echo Instalando librerias de Python...
python -m pip install --upgrade pip
pip install -r requirements.txt
echo Inicializando Base de Datos...
python -c "from app import db, create_app; app=create_app(); with app.app_context(): db.create_all()"
cd ..

:: 4. Preparar Frontend
echo.
echo [2/3] Instalando dependencias del Frontend...
cd frontend
call npm install
echo.
echo [3/3] Construyendo aplicacion (Build)...
call npm run build
cd ..

echo.
echo ====================================================
echo   INSTALACION COMPLETADA EXITOSAMENTE
echo ====================================================
echo.
echo Ahora puedes cerrar esta ventana y usar 'start-windows.bat'
echo para iniciar el sistema.
echo.
pause
