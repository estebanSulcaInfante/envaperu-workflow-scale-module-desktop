@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Mesa.ps1" -Accion Instalar
if errorlevel 1 pause
