@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=backend\venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=backend\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] No se encontro el entorno Python del modulo.
    exit /b 2
)

"%PYTHON_EXE%" backend\station_storage.py backup --reason daily
exit /b %ERRORLEVEL%
