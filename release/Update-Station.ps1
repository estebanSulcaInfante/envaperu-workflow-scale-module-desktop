param(
    [Parameter(Mandatory = $true)]
    [string]$PackagePath,
    [string]$ExpectedSha256,
    [string]$InstallRoot = "$env:ProgramFiles\EnvaPeru\Pesaje",
    [string]$DataRoot = "$env:ProgramData\EnvaPeru\Pesaje",
    [string]$StationId = 'PESAJE-PLANTA-01',
    [int]$Port = 5050,
    [switch]$SkipRuntimeInstall,
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-CheckedPython {
    param([string]$Python, [string[]]$Arguments, [string]$FailureMessage)
    $output = @(& $Python @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage`n$($output -join [Environment]::NewLine)"
    }
    return $output
}

function Get-LastJson {
    param([object[]]$Output)
    $reversed = @($Output)
    [array]::Reverse($reversed)
    foreach ($line in $reversed) {
        try { return ($line.ToString() | ConvertFrom-Json) } catch { }
    }
    throw 'La operacion no devolvio un resultado JSON verificable.'
}

function Find-BootstrapPython {
    $candidate = Get-Command python -ErrorAction SilentlyContinue
    if ($candidate) {
        & $candidate.Source -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate.Source }
    }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $resolved = @(& $launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null)
        if ($LASTEXITCODE -eq 0 -and $resolved.Count -gt 0 -and (Test-Path -LiteralPath $resolved[-1])) {
            return [IO.Path]::GetFullPath($resolved[-1])
        }
    }
    throw 'Se requiere Python 3.12 en PATH para instalar o actualizar la estacion.'
}

function Wait-StationState {
    param([bool]$Ready, [int]$TimeoutSeconds = 30)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/local/v1/health/ready" -TimeoutSec 2
            if ($Ready -and $response.status -eq 'READY') { return $true }
        }
        catch {
            if (-not $Ready) { return $true }
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function Stop-Release {
    param([string]$ReleasePath)
    if (-not $ReleasePath) { return }
    $python = Join-Path $ReleasePath 'backend\venv\Scripts\python.exe'
    $control = Join-Path $ReleasePath 'backend\station_control.py'
    if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $control)) { return }
    & $python $control stop --station-id $StationId | Out-Host
    if ($LASTEXITCODE -notin @(0, 4)) {
        throw "No se pudo detener ordenadamente la estacion (codigo $LASTEXITCODE)."
    }
    if (-not (Wait-StationState -Ready $false -TimeoutSeconds 20)) {
        throw 'La estacion no libero el puerto dentro del tiempo permitido.'
    }
}

$PackagePath = [IO.Path]::GetFullPath($PackagePath)
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) {
    throw "No existe el paquete $PackagePath"
}
if ([string]::IsNullOrWhiteSpace($ExpectedSha256)) {
    $sidecar = "$PackagePath.sha256"
    if (-not (Test-Path -LiteralPath $sidecar)) {
        throw 'Falta el SHA-256 esperado o su archivo .sha256.'
    }
    $ExpectedSha256 = ((Get-Content -LiteralPath $sidecar -Raw) -split '\s+')[0]
}

$bootstrapPython = Find-BootstrapPython
$statePath = Join-Path $DataRoot 'run\active-release.json'
$previousState = $null
if (Test-Path -LiteralPath $statePath) {
    $previousState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
}
$managerScript = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\backend\station_release.py'))
if (-not (Test-Path -LiteralPath $managerScript) -and $previousState) {
    $managerScript = Join-Path ([string]$previousState.active_path) 'backend\station_release.py'
}
if (-not (Test-Path -LiteralPath $managerScript)) {
    throw 'No se encontro el gestor de releases de una instalacion confiable.'
}

$stageOutput = Invoke-CheckedPython $bootstrapPython @(
    $managerScript, 'stage', '--package', $PackagePath,
    '--install-root', $InstallRoot, '--expected-sha256', $ExpectedSha256
) 'El paquete no supero la verificacion'
$stage = (Get-LastJson $stageOutput)
$releasePath = [string]$stage.release_path
$version = [string]$stage.version
$newPython = Join-Path $releasePath 'backend\venv\Scripts\python.exe'

if (-not $SkipRuntimeInstall -and -not (Test-Path -LiteralPath $newPython)) {
    & $bootstrapPython -m venv (Join-Path $releasePath 'backend\venv')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno Python del nuevo release.' }
    $runtimeLock = Join-Path $releasePath 'backend\requirements-runtime.lock'
    $wheelhouse = Join-Path $releasePath 'wheels'
    & $newPython -m pip install --no-index --find-links $wheelhouse --requirement $runtimeLock
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias offline.' }
    & $newPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'El runtime instalado tiene dependencias incompatibles.' }
}
if (-not $SkipRuntimeInstall -and -not (Test-Path -LiteralPath $newPython)) {
    throw 'El nuevo release no contiene un runtime Python utilizable.'
}

$backupPath = $null
$databasePath = Join-Path $DataRoot 'data\pesajes.db'
$backupPython = $newPython
$backupStorage = Join-Path $releasePath 'backend\station_storage.py'
if ($previousState) {
    $candidate = Join-Path ([string]$previousState.active_path) 'backend\venv\Scripts\python.exe'
    $candidateStorage = Join-Path ([string]$previousState.active_path) 'backend\station_storage.py'
    if (Test-Path -LiteralPath $candidate) {
        $backupPython = $candidate
        $backupStorage = $candidateStorage
    }
}

if ((Test-Path -LiteralPath $databasePath) -and -not $SkipRuntimeInstall) {
    $backupOutput = Invoke-CheckedPython $backupPython @(
        $backupStorage, '--data-root', $DataRoot, '--station-id', $StationId,
        'backup', '--reason', "pre-update-$version"
    ) 'No se pudo crear el backup previo a la actualizacion'
    $backupResult = Get-LastJson $backupOutput
    $backupPath = [string]$backupResult.backup.path

    $preflightRoot = Join-Path $DataRoot "run\update-preflight-$([guid]::NewGuid().ToString('N'))"
    try {
        New-Item -ItemType Directory -Path (Join-Path $preflightRoot 'data') -Force | Out-Null
        Copy-Item -LiteralPath $backupPath -Destination (Join-Path $preflightRoot 'data\pesajes.db')
        Invoke-CheckedPython $newPython @(
            (Join-Path $releasePath 'backend\station_storage.py'),
            '--data-root', $preflightRoot, '--station-id', $StationId, 'migrate'
        ) 'La migracion de prueba fallo sobre una copia de la base' | Out-Null
    }
    finally {
        $resolvedPreflight = [IO.Path]::GetFullPath($preflightRoot)
        $resolvedRun = [IO.Path]::GetFullPath((Join-Path $DataRoot 'run'))
        if ((Test-Path -LiteralPath $resolvedPreflight) -and $resolvedPreflight.StartsWith($resolvedRun + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedPreflight -Recurse -Force
        }
    }
}

$previousPath = if ($previousState) { [string]$previousState.active_path } else { $null }
if ($previousPath) { Stop-Release $previousPath }

$activateOutput = Invoke-CheckedPython $bootstrapPython @(
    $managerScript, 'activate', '--version', $version,
    '--install-root', $InstallRoot, '--data-root', $DataRoot,
    '--preupdate-backup', ([string]$backupPath)
) 'No se pudo activar el nuevo release'
$activateOutput | Out-Host

if ($NoStart) {
    Write-Output "UPDATE_STAGED version=$version start=deferred"
    exit 0
}

try {
    & (Join-Path $releasePath 'release\Start-ActiveStation.ps1') -InstallRoot $InstallRoot -DataRoot $DataRoot -StationId $StationId -Port $Port
    if (-not (Wait-StationState -Ready $true -TimeoutSeconds 45)) {
        throw 'El nuevo release no alcanzo readiness.'
    }
    $pilotPreflightOutput = Invoke-CheckedPython $newPython @(
        (Join-Path $releasePath 'backend\station_control.py'),
        'validate-pilot-config', '--data-root', $DataRoot
    ) 'La configuracion central minima del piloto es invalida'
    $pilotPreflight = Get-LastJson $pilotPreflightOutput
    if (-not [bool]$pilotPreflight.valid) {
        throw 'La configuracion central minima del piloto es invalida.'
    }
    Write-Output "PILOT_CONFIG_READY station_id=$($pilotPreflight.station_id) operator_id=$($pilotPreflight.scm_operator_id)"
    $launcherRoot = Join-Path $InstallRoot 'launcher'
    New-Item -ItemType Directory -Path $launcherRoot -Force | Out-Null
    @(
        'Install-StationTask.ps1',
        'Rollback-Station.ps1',
        'Start-ActiveStation.ps1',
        'Update-Station.ps1'
    ) | ForEach-Object {
        Copy-Item -LiteralPath (Join-Path $releasePath "release\$_") -Destination (Join-Path $launcherRoot $_) -Force
    }
    Write-Output "UPDATE_COMPLETE version=$version backup=$backupPath"
}
catch {
    $updateError = $_
    Stop-Release $releasePath
    if (-not $previousState) {
        throw "La primera instalacion fallo y no existe un release anterior: $updateError"
    }
    Invoke-CheckedPython $bootstrapPython @(
        $managerScript, 'rollback', '--install-root', $InstallRoot, '--data-root', $DataRoot
    ) 'No se pudo restaurar el puntero del release anterior' | Out-Host
    if ($backupPath) {
        $previousPython = Join-Path $previousPath 'backend\venv\Scripts\python.exe'
        Invoke-CheckedPython $previousPython @(
            (Join-Path $previousPath 'backend\station_storage.py'),
            '--data-root', $DataRoot, '--station-id', $StationId,
            'restore', $backupPath
        ) 'No se pudo restaurar la base previa a la actualizacion' | Out-Host
    }
    & (Join-Path $previousPath 'release\Start-ActiveStation.ps1') -InstallRoot $InstallRoot -DataRoot $DataRoot -StationId $StationId -Port $Port
    if (-not (Wait-StationState -Ready $true -TimeoutSeconds 45)) {
        throw "Fallo el release nuevo y el anterior no recupero readiness. Error inicial: $updateError"
    }
    throw "La actualizacion fue revertida; la version anterior esta operativa. Error: $updateError"
}
