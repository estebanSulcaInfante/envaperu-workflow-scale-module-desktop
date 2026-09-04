param(
    [string]$InstallRoot = "$env:ProgramFiles\EnvaPeru\Pesaje",
    [string]$DataRoot = "$env:ProgramData\EnvaPeru\Pesaje",
    [string]$StationId = 'PESAJE-PLANTA-01',
    [int]$Port = 5050,
    [Parameter(Mandatory = $true)]
    [switch]$ConfirmNoCapturesSinceUpdate
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $ConfirmNoCapturesSinceUpdate) {
    throw 'El rollback manual exige confirmar que no hubo capturas desde la actualizacion.'
}

$statePath = Join-Path $DataRoot 'run\active-release.json'
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if (-not $state.previous_path) { throw 'No existe un release anterior para recuperar.' }

$activePython = Join-Path ([string]$state.active_path) 'backend\venv\Scripts\python.exe'
& $activePython (Join-Path ([string]$state.active_path) 'backend\station_control.py') stop --station-id $StationId
if ($LASTEXITCODE -notin @(0, 4)) { throw 'No se pudo detener la estacion activa.' }
Start-Sleep -Seconds 2

$manager = Join-Path ([string]$state.active_path) 'backend\station_release.py'
& $activePython $manager rollback --install-root $InstallRoot --data-root $DataRoot
if ($LASTEXITCODE -ne 0) { throw 'No se pudo restaurar el puntero anterior.' }

if ($state.preupdate_backup) {
    $previousPython = Join-Path ([string]$state.previous_path) 'backend\venv\Scripts\python.exe'
    & $previousPython (Join-Path ([string]$state.previous_path) 'backend\station_storage.py') `
        --data-root $DataRoot --station-id $StationId restore ([string]$state.preupdate_backup)
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo restaurar la base previa.' }
}

& (Join-Path ([string]$state.previous_path) 'release\Start-ActiveStation.ps1') `
    -InstallRoot $InstallRoot -DataRoot $DataRoot -StationId $StationId -Port $Port
Write-Output "ROLLBACK_COMPLETE version=$($state.previous_version)"
