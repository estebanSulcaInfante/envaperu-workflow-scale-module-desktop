param(
    [ValidateSet("stop")]
    [string]$Command = "stop",
    [string]$StationId = "PESAJE-PLANTA-01"
)

$moduleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $moduleRoot "backend\venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $moduleRoot "backend\.venv\Scripts\python.exe"
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "No se encontro el entorno Python de la estacion."
    exit 2
}

& $python (Join-Path $moduleRoot "backend\station_control.py") $Command --station-id $StationId
exit $LASTEXITCODE

