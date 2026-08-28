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
    throw 'La operación no devolvió evidencia JSON verificable.'
}

function Test-LoopbackPortOpen {
    try {
        return @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        ).Count -gt 0
    }
    catch {
        $netstatLines = @(netstat -ano -p tcp 2>$null)
        if ($LASTEXITCODE -eq 0) {
            $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+\d+\s*$"
            return @($netstatLines | Select-String -Pattern $pattern).Count -gt 0
        }
    }
    $client = New-Object System.Net.Sockets.TcpClient
    $connection = $null
    try {
        $connection = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $connection.AsyncWaitHandle.WaitOne(1000, $false)) {
            return $true
        }
        try {
            $client.EndConnect($connection)
            return $client.Connected
        }
        catch {
            return $false
        }
    }
    finally {
        if ($connection -and $connection.AsyncWaitHandle) {
            $connection.AsyncWaitHandle.Close()
        }
        $client.Close()
    }
}

function Wait-StationStopped {
    param([int]$TimeoutSeconds = 20)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $readyResponding = $false
        try {
            $null = Invoke-RestMethod `
                -Uri "http://127.0.0.1:$Port/api/local/v1/health/ready" `
                -TimeoutSec 1
            $readyResponding = $true
        }
        catch { }

        if (-not $readyResponding -and -not (Test-LoopbackPortOpen)) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function Wait-StationReady {
    param(
        [string]$ExpectedVersion,
        [int]$TimeoutSeconds = 45,
        [switch]$AllowMissingVersion
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-RestMethod `
                -Uri "http://127.0.0.1:$Port/api/local/v1/health/ready" `
                -TimeoutSec 2
            $responseVersion = $null
            if ($response.PSObject.Properties['app_version']) {
                $responseVersion = [string]$response.app_version
            }
            if (
                $response.status -eq 'READY' -and
                (
                    $responseVersion -eq $ExpectedVersion -or
                    (
                        $AllowMissingVersion -and
                        [string]::IsNullOrWhiteSpace($responseVersion)
                    )
                )
            ) {
                return $true
            }
        }
        catch { }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function Assert-RollbackEvidence {
    param(
        [string]$Python,
        [string]$StorageScript,
        [string]$BackupPath,
        [string]$ValidationBaselinePath
    )
    if (
        [string]::IsNullOrWhiteSpace($BackupPath) -or
        [string]::IsNullOrWhiteSpace($ValidationBaselinePath)
    ) {
        throw 'Este release no conserva backup previo y línea base posmigración. El rollback automático no es demostrablemente seguro.'
    }
    foreach ($candidate in @($BackupPath, $ValidationBaselinePath)) {
        $verifyOutput = Invoke-CheckedPython $Python @(
            $StorageScript, '--data-root', $DataRoot, '--station-id', $StationId,
            'verify', $candidate
        ) "Backup de rollback inválido: $candidate"
        $verified = Get-LastJson $verifyOutput
        if ([string]$verified.backup.station_id -ne $StationId) {
            throw "El backup $candidate pertenece a otra estación."
        }
    }

    $comparisonOutput = @(& $Python $StorageScript `
        --data-root $DataRoot --station-id $StationId `
        compare-operational $ValidationBaselinePath 2>&1)
    $comparisonExit = $LASTEXITCODE
    if ($comparisonExit -ne 0) {
        throw "Hay deltas en pesajes, impresiones, correcciones o acuses; se rechaza el rollback para evitar pérdida de datos.`n$($comparisonOutput -join [Environment]::NewLine)"
    }
    $comparison = Get-LastJson $comparisonOutput
    if ([string]$comparison.event -ne 'OPERATIONAL_STATE_MATCH') {
        throw 'La comparación no confirmó igualdad con la línea base posmigración.'
    }
}

$statePath = Join-Path $DataRoot 'run\active-release.json'
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if (-not $state.previous_path) { throw 'No existe un release anterior para recuperar.' }
if (-not $state.preupdate_backup) { throw 'El release activo no registra un backup previo verificable.' }
if (-not $state.PSObject.Properties['validation_baseline'] -or -not $state.validation_baseline) {
    throw 'El release activo no registra una línea base posmigración; el rollback seguro requiere conciliación manual.'
}

$activePython = Join-Path ([string]$state.active_path) 'backend\venv\Scripts\python.exe'
$activeStorage = Join-Path ([string]$state.active_path) 'backend\station_storage.py'
& $activePython (Join-Path ([string]$state.active_path) 'backend\station_control.py') stop --station-id $StationId
if ($LASTEXITCODE -notin @(0, 4)) { throw 'No se pudo detener la estacion activa.' }
if (-not (Wait-StationStopped -TimeoutSeconds 20)) {
    throw 'La estacion no libero el puerto dentro del tiempo permitido; no se restauro la base.'
}


Assert-RollbackEvidence `
    -Python $activePython `
    -StorageScript $activeStorage `
    -BackupPath ([string]$state.preupdate_backup) `
    -ValidationBaselinePath ([string]$state.validation_baseline)

$manager = Join-Path ([string]$state.active_path) 'backend\station_release.py'
Invoke-CheckedPython $activePython @(
    $manager, 'rollback', '--install-root', $InstallRoot, '--data-root', $DataRoot
) 'No se pudo restaurar el puntero anterior.' | Out-Host

try {
    # Segunda barrera inmediatamente antes de restaurar: una escritura externa
    # no puede quedar oculta en la pequeña ventana del cambio de puntero.
    Assert-RollbackEvidence `
        -Python $activePython `
        -StorageScript $activeStorage `
        -BackupPath ([string]$state.preupdate_backup) `
        -ValidationBaselinePath ([string]$state.validation_baseline)
}
catch {
    Invoke-CheckedPython $activePython @(
        $manager, 'rollback', '--install-root', $InstallRoot, '--data-root', $DataRoot
    ) 'La base cambió durante el rollback y no se pudo recuperar el puntero original.' | Out-Null
    throw "La base cambió durante el cambio de puntero. Se recuperó el release nuevo y no se restauró ningún backup. Evidencia: $_"
}

$previousPython = Join-Path ([string]$state.previous_path) 'backend\venv\Scripts\python.exe'
Invoke-CheckedPython $previousPython @(
    (Join-Path ([string]$state.previous_path) 'backend\station_storage.py'),
    '--data-root', $DataRoot, '--station-id', $StationId,
    'restore', ([string]$state.preupdate_backup)
) 'No se pudo restaurar la base previa.' | Out-Host

& (Join-Path ([string]$state.previous_path) 'release\Start-ActiveStation.ps1') `
    -InstallRoot $InstallRoot -DataRoot $DataRoot -StationId $StationId -Port $Port
if (-not (Wait-StationReady -ExpectedVersion ([string]$state.previous_version) -AllowMissingVersion)) {
    throw 'El puntero y la base fueron restaurados, pero el release anterior no alcanzó READY con su versión esperada.'
}
Write-Output "ROLLBACK_COMPLETE version=$($state.previous_version)"
