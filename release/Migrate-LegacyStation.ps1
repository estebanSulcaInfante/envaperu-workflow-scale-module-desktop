param(
    [Parameter(Mandatory = $true)]
    [string]$PackagePath,
    [string]$ExpectedSha256,
    [Parameter(Mandatory = $true)]
    [string]$LegacyDatabasePath,
    [string]$LegacyEnvironmentPath,
    [Parameter(Mandatory = $true)]
    [string]$StationUuid,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$ScmOperatorId,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{1,63}$')]
    [string]$StationCode = 'PESAJE-PLANTA-01',
    [string]$CentralOrigin = 'https://envaperu-scm-api.onrender.com',
    [string]$InstallRoot = "$env:ProgramFiles\EnvaPeru\Pesaje",
    [string]$DataRoot = "$env:ProgramData\EnvaPeru\Pesaje",
    [int]$Port = 5050,
    [string]$RunAsUser
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
    throw 'La operación no devolvió evidencia JSON verificable.'
}

function Test-Python312 {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    & $Path -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>$null
    return $LASTEXITCODE -eq 0
}

function Find-BootstrapPython {
    param([string[]]$TrustedLegacyCandidates = @())

    # Una PC legacy puede no exponer Python en PATH, aunque su entorno virtual
    # siga siendo utilizable. Solo se consideran candidatos derivados de la
    # ruta legacy que el operador seleccionó explícitamente.
    foreach ($trustedCandidate in $TrustedLegacyCandidates) {
        if (Test-Python312 $trustedCandidate) {
            return [IO.Path]::GetFullPath($trustedCandidate)
        }
    }
    $candidate = Get-Command python -ErrorAction SilentlyContinue
    if ($candidate -and (Test-Python312 $candidate.Source)) {
        return $candidate.Source
    }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $resolved = @(& $launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null)
        if ($LASTEXITCODE -eq 0 -and $resolved.Count -gt 0 -and (Test-Path -LiteralPath $resolved[-1])) {
            return [IO.Path]::GetFullPath($resolved[-1])
        }
    }
    throw 'No se encontró Python 3.12 en la instalación legacy, PATH ni el launcher py. No se modificó la base; instale el runtime aprobado antes de migrar.'
}

function Read-EnvironmentFile {
    param([string]$Path)
    $values = @{}
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $values
    }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) {
            return
        }
        $name, $value = $line.Split('=', 2)
        $name = $name.Trim()
        if ($name -match '^[A-Za-z_][A-Za-z0-9_]*$') {
            $values[$name] = $value.Trim()
        }
    }
    return $values
}

function ConvertFrom-LegacyEnvironmentValue {
    param([AllowNull()][string]$Value)

    if ($null -eq $Value) { return '' }
    $normalized = $Value.Trim()
    if ($normalized.Length -ge 2) {
        $first = $normalized.Substring(0, 1)
        $last = $normalized.Substring($normalized.Length - 1, 1)
        if (
            ($first -eq '"' -and $last -eq '"') -or
            ($first -eq "'" -and $last -eq "'")
        ) {
            return $normalized.Substring(1, $normalized.Length - 2)
        }
    }
    return $normalized
}

function Select-LegacyValue {
    param([hashtable]$Values, [string]$Name, [string]$Default)
    if ($Values.ContainsKey($Name) -and -not [string]::IsNullOrWhiteSpace([string]$Values[$Name])) {
        return ConvertFrom-LegacyEnvironmentValue ([string]$Values[$Name])
    }
    return $Default
}

function Test-PortListening {
    param([int]$LocalPort)
    try {
        return @(
            Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction Stop
        ).Count -gt 0
    }
    catch {
        # No depender del idioma del texto de estado de netstat.
        $pattern = "^\s*TCP\s+\S+:$LocalPort\s+\S+\s+\S+\s+\d+\s*$"
        return @(netstat -ano -p tcp 2>$null | Select-String -Pattern $pattern).Count -gt 0
    }
}

$PackagePath = [IO.Path]::GetFullPath($PackagePath)
$LegacyDatabasePath = [IO.Path]::GetFullPath($LegacyDatabasePath)
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
$legacyInstance = Split-Path -Parent $LegacyDatabasePath
$legacyBackend = Split-Path -Parent $legacyInstance
$legacyRoot = Split-Path -Parent $legacyBackend
if ($LegacyEnvironmentPath) {
    $LegacyEnvironmentPath = [IO.Path]::GetFullPath($LegacyEnvironmentPath)
}
else {
    $candidateEnvironment = Join-Path $legacyRoot '.env'
    if (Test-Path -LiteralPath $candidateEnvironment -PathType Leaf) {
        $LegacyEnvironmentPath = $candidateEnvironment
    }
}

if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) {
    throw "No existe el paquete $PackagePath"
}
if (-not (Test-Path -LiteralPath $LegacyDatabasePath -PathType Leaf)) {
    throw "No existe la base legacy $LegacyDatabasePath"
}
$destinationDatabase = Join-Path $DataRoot 'data\pesajes.db'
if ([IO.Path]::GetFullPath($destinationDatabase) -eq $LegacyDatabasePath) {
    throw 'La base legacy y el destino versionado no pueden ser el mismo archivo.'
}
$statePath = Join-Path $DataRoot 'run\active-release.json'
if (Test-Path -LiteralPath $statePath -PathType Leaf) {
    throw 'La estación ya tiene active-release.json. Use Update-Station.ps1; no reimporte la base legacy.'
}
if (Test-Path -LiteralPath $destinationDatabase -PathType Leaf) {
    throw 'ProgramData ya contiene pesajes.db sin release activo. Es una instalación parcial: detenerse, respaldar y conciliar; no reimportar automáticamente.'
}
if (Test-PortListening $Port) {
    throw "El puerto $Port sigue en escucha. Cierre completamente la estación legacy antes de migrar."
}

try {
    [void][Guid]::Parse($StationUuid)
}
catch {
    throw 'StationUuid debe ser el UUID real provisionado en Central.'
}
$centralUri = $null
try { $centralUri = [Uri]$CentralOrigin } catch { }
if ($null -eq $centralUri -or -not $centralUri.IsAbsoluteUri -or $centralUri.Scheme -ne 'https') {
    throw 'CentralOrigin debe ser una URL HTTPS absoluta.'
}

$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
if ([string]::IsNullOrWhiteSpace($RunAsUser)) { $RunAsUser = $currentUser }
if (-not [string]::Equals($RunAsUser, $currentUser, [StringComparison]::OrdinalIgnoreCase)) {
    throw "El token DPAPI debe provisionarse con el usuario operativo $RunAsUser. Ejecute este puente iniciando sesión como ese usuario; usuario actual: $currentUser"
}

if ([string]::IsNullOrWhiteSpace($ExpectedSha256)) {
    $sidecar = "$PackagePath.sha256"
    if (-not (Test-Path -LiteralPath $sidecar -PathType Leaf)) {
        throw 'Falta el SHA-256 esperado o su archivo .sha256.'
    }
    $ExpectedSha256 = ((Get-Content -LiteralPath $sidecar -Raw) -split '\s+')[0]
}
$ExpectedSha256 = $ExpectedSha256.Trim().ToLowerInvariant()
if ($ExpectedSha256 -notmatch '^[0-9a-f]{64}$') {
    throw 'El SHA-256 esperado debe contener 64 caracteres hexadecimales.'
}

$legacyPythonCandidates = @(
    (Join-Path $legacyBackend '.venv\Scripts\python.exe'),
    (Join-Path $legacyBackend 'venv\Scripts\python.exe'),
    (Join-Path $legacyRoot '.venv\Scripts\python.exe'),
    (Join-Path $legacyRoot 'venv\Scripts\python.exe')
)
$bootstrapPython = Find-BootstrapPython -TrustedLegacyCandidates $legacyPythonCandidates
$managerScript = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\backend\station_release.py'))
if (-not (Test-Path -LiteralPath $managerScript -PathType Leaf)) {
    throw 'Ejecute Migrate-LegacyStation.ps1 desde el paquete extraído del release.'
}

# Stage verifica el ZIP y su manifiesto, pero deliberadamente no activa ningún puntero.
$stageOutput = Invoke-CheckedPython $bootstrapPython @(
    $managerScript, 'stage', '--package', $PackagePath,
    '--install-root', $InstallRoot, '--expected-sha256', $ExpectedSha256
) 'El paquete no superó la verificación'
$stage = Get-LastJson $stageOutput
$releasePath = [string]$stage.release_path
$version = [string]$stage.version
$newPython = Join-Path $releasePath 'backend\venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $newPython -PathType Leaf)) {
    & $bootstrapPython -m venv (Join-Path $releasePath 'backend\venv')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el runtime Python del release.' }
}
$runtimeLock = Join-Path $releasePath 'backend\requirements-runtime.lock'
$wheelhouse = Join-Path $releasePath 'wheels'
& $newPython -m pip install --no-index --find-links $wheelhouse --requirement $runtimeLock
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias offline.' }
& $newPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'El runtime instalado tiene dependencias incompatibles.' }

$legacyValues = Read-EnvironmentFile $LegacyEnvironmentPath
$stationEnvironment = [ordered]@{
    STATION_CODE = $StationCode
    STATION_UUID = $StationUuid
    STATION_MODE = 'MONITORED_LEGACY'
    SCM_OPERATOR_ID = [string]$ScmOperatorId
    CENTRAL_ORIGIN = $centralUri.AbsoluteUri.TrimEnd('/')
    ALLOW_INSECURE_CENTRAL = 'false'
    MONITORING_ENABLED = 'true'
    SYNC_ENABLED = 'false'
    PORTFOLIO_DEMO_MODE = 'false'
    ALLOW_SCALE_SIMULATION = 'false'
    ALLOW_LOCAL_SCM_DEMO = 'false'
    SIMULATE_PRINTER = 'false'
    TIMEZONE = (Select-LegacyValue $legacyValues 'TIMEZONE' 'America/Lima')
    SCALE_PORT = (Select-LegacyValue $legacyValues 'SCALE_PORT' 'COM4')
    SCALE_BAUD_RATE = (Select-LegacyValue $legacyValues 'SCALE_BAUD_RATE' '9600')
    PRINTER_TYPE = (Select-LegacyValue $legacyValues 'PRINTER_TYPE' 'TSPL')
    PRINTER_NAME = (Select-LegacyValue $legacyValues 'PRINTER_NAME' 'TSC TE200')
    PRINTER_PORT = (Select-LegacyValue $legacyValues 'PRINTER_PORT' 'COM3')
    BACKUP_RETENTION_COUNT = (Select-LegacyValue $legacyValues 'BACKUP_RETENTION_COUNT' '14')
    LOG_FILE_LEVEL = (Select-LegacyValue $legacyValues 'LOG_FILE_LEVEL' 'INFO')
    LOG_CONSOLE_LEVEL = (Select-LegacyValue $legacyValues 'LOG_CONSOLE_LEVEL' 'INFO')
    LOG_MAX_BYTES = (Select-LegacyValue $legacyValues 'LOG_MAX_BYTES' '10485760')
    LOG_BACKUP_COUNT = (Select-LegacyValue $legacyValues 'LOG_BACKUP_COUNT' '10')
    HEARTBEAT_SECONDS = (Select-LegacyValue $legacyValues 'HEARTBEAT_SECONDS' '30')
}
$configRoot = Join-Path $DataRoot 'config'
$backupRoot = Join-Path $DataRoot 'backups'
New-Item -ItemType Directory -Path $configRoot -Force | Out-Null
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
$stationEnvironmentPath = Join-Path $configRoot 'station.env'
if (Test-Path -LiteralPath $stationEnvironmentPath -PathType Leaf) {
    $configBackup = Join-Path $backupRoot (
        'station.env.pre-legacy-migration.' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    )
    Copy-Item -LiteralPath $stationEnvironmentPath -Destination $configBackup
}
$environmentLines = @(
    '# Generado por Migrate-LegacyStation.ps1; no contiene tokens.'
)
foreach ($entry in $stationEnvironment.GetEnumerator()) {
    $environmentLines += "$($entry.Key)=$($entry.Value)"
}
Set-Content -LiteralPath $stationEnvironmentPath -Value $environmentLines -Encoding UTF8

Write-Output "PACKAGE_STAGED version=$version path=$releasePath"
Write-Output "CONFIG_PREPARED path=$stationEnvironmentPath legacy_env=$LegacyEnvironmentPath"
Write-Output 'Ingrese ahora el token de la estación provisto por Central. No se mostrará ni se guardará en station.env.'
& $newPython (Join-Path $releasePath 'backend\station_control.py') `
    provision-token --data-root $DataRoot
if ($LASTEXITCODE -ne 0) { throw 'No se pudo provisionar el token DPAPI.' }
if (Test-PortListening $Port) {
    throw "La estación legacy volvió a iniciar en el puerto $Port. Deshabilite su arranque automático antes de importar."
}

$importOutput = Invoke-CheckedPython $newPython @(
    (Join-Path $releasePath 'backend\station_storage.py'),
    '--data-root', $DataRoot, '--station-id', $StationCode,
    'import-legacy', $LegacyDatabasePath
) 'La base legacy no superó la importación segura'
$importResult = Get-LastJson $importOutput
if (
    [string]$importResult.event -ne 'LEGACY_IMPORT_COMPLETE' -or
    -not [bool]$importResult.source_unchanged -or
    [string]$importResult.destination.integrity_check -ne 'ok'
) {
    throw 'La importación no produjo evidencia completa: LEGACY_IMPORT_COMPLETE, source_unchanged=true e integrity_check=ok son obligatorios.'
}
$evidencePath = Join-Path $backupRoot (
    'legacy-migration-evidence-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '.json'
)
$importResult | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $evidencePath -Encoding UTF8
Write-Output "LEGACY_IMPORT_VERIFIED evidence=$evidencePath"
if (Test-PortListening $Port) {
    throw "La estación legacy volvió a iniciar en el puerto $Port. La fuente quedó intacta y el release nuevo no fue activado."
}

& $newPython (Join-Path $releasePath 'backend\station_control.py') `
    initialize-identity `
    --data-root $DataRoot `
    --station-uuid $StationUuid `
    --station-code $StationCode
if ($LASTEXITCODE -ne 0) {
    throw 'No se pudo fijar en la base importada la identidad UUID/código provisionada por Central.'
}
Write-Output "STATION_IDENTITY_READY station_uuid=$StationUuid station_code=$StationCode"

$updateScript = Join-Path $PSScriptRoot 'Update-Station.ps1'
$updateOutput = @(& $updateScript `
    -PackagePath $PackagePath `
    -ExpectedSha256 $ExpectedSha256 `
    -InstallRoot $InstallRoot `
    -DataRoot $DataRoot `
    -StationId $StationCode `
    -Port $Port `
    -PreparedLegacyMigration 2>&1)
$updateOutput | Out-Host
if (-not @($updateOutput | Where-Object { $_.ToString() -like 'PILOT_CONFIG_READY*' })) {
    throw 'La activación no confirmó PILOT_CONFIG_READY.'
}
if (-not @($updateOutput | Where-Object { $_.ToString() -like 'UPDATE_COMPLETE*' })) {
    throw 'La activación no confirmó UPDATE_COMPLETE.'
}

Write-Output "LEGACY_MIGRATION_COMPLETE version=$version source_unchanged=true evidence=$evidencePath"
