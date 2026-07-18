@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=backend\venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=backend\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] No se encontro el entorno Python del modulo.
    exit /b 2
)

"%PYTHON_EXE%" backend\station_control.py stop --station-id PESAJE-PLANTA-01
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" (
    echo Parada ordenada solicitada.
) else if "%EXIT_CODE%"=="4" (
    echo La estacion no esta ejecutandose.
) else (
    echo [ERROR] No se pudo solicitar la parada. Codigo %EXIT_CODE%.
)

exit /b %EXIT_CODE%
