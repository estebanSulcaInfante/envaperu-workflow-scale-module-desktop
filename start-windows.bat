@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=backend\venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=backend\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] No se encontro el entorno Python del modulo.
    echo Ejecuta install-windows.bat antes de iniciar la estacion.
    pause
    exit /b 2
)

if not exist "frontend\dist\index.html" (
    echo [ERROR] No se encontro el frontend compilado.
    echo Ejecuta install-windows.bat o npm run build dentro de frontend.
    pause
    exit /b 2
)

echo Iniciando Estacion de Pesaje ENVAPERU...
echo URL local: http://127.0.0.1:5050
"%PYTHON_EXE%" backend\station_main.py --open-browser
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="73" (
    echo La estacion ya estaba ejecutandose. Abriendo la interfaz existente...
    start "" "http://127.0.0.1:5050"
    exit /b 0
)

if not "%EXIT_CODE%"=="0" (
    echo [ERROR] La estacion finalizo con codigo %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
