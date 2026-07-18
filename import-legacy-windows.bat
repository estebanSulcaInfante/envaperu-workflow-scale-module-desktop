@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=backend\venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=backend\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] No se encontro el entorno Python del modulo.
    exit /b 2
)

if "%~1"=="" (
    echo Uso: import-legacy-windows.bat "C:\ruta\pesajes.db"
    echo La estacion debe estar detenida antes de ejecutar este comando.
    exit /b 2
)

if not exist "%~1" (
    echo [ERROR] No existe la base SQLite indicada: %~1
    exit /b 2
)

netstat -ano | findstr ":5050" | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo [ERROR] El puerto 5050 sigue en escucha. Deten el backend antiguo antes de importar.
    exit /b 6
)

set "REPLACE_ARG="
if not "%~2"=="" (
    if /I not "%~2"=="--replace-existing" (
        echo [ERROR] Segundo argumento no reconocido: %~2
        exit /b 2
    )
    set "REPLACE_ARG=--replace-existing"
)
if not "%~3"=="" (
    echo [ERROR] Demasiados argumentos.
    exit /b 2
)

for %%I in ("%~1") do set "SOURCE_DB=%%~fI"

echo Validando e importando SQLite mediante backup consistente...
echo Origen: "%SOURCE_DB%"
"%PYTHON_EXE%" backend\station_storage.py import-legacy "%SOURCE_DB%" %REPLACE_ARG%
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" (
    echo [OK] Importacion verificada. La base de origen no fue copiada con COPY ni XCOPY.
) else (
    echo [ERROR] Importacion cancelada con codigo %EXIT_CODE%. La base de origen no fue modificada.
)

exit /b %EXIT_CODE%
