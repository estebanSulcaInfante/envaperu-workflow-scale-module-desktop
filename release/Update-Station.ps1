param(
    [Parameter(Mandatory = $true)]
    [string]$PackagePath,
    [string]$ExpectedSha256,
    [string]$BootstrapPythonPath,
    [string]$InstallRoot = "$env:ProgramFiles\EnvaPeru\Pesaje",
    [string]$DataRoot = "$env:ProgramData\EnvaPeru\Pesaje",
    [string]$StationId = 'PESAJE-PLANTA-01',
    [int]$Port = 5050,
    [string]$TaskName = 'EnvaPeru Pesaje Edge',
    [switch]$SkipRuntimeInstall,
    [switch]$NoStart,
    [switch]$PreparedLegacyMigration,
    [switch]$AllowEmptyStation,
    [switch]$ResumeFirstActivation
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

function Test-LoopbackPortOpen {
    try {
        return @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        ).Count -gt 0
    }
    catch {
        $netstatLines = @(netstat -ano -p tcp 2>$null)
        if ($LASTEXITCODE -eq 0) {
            $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+\S+\s+\d+\s*$"
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

function Resolve-AccountSid {
    param([string]$Account)
    if ([string]::IsNullOrWhiteSpace($Account)) { return $null }
    try {
        if ($Account -match '^S-1-') { return $Account }
        $principal = New-Object Security.Principal.NTAccount($Account)
        return $principal.Translate([Security.Principal.SecurityIdentifier]).Value
    }
    catch { return $null }
}

function Find-BootstrapPython {
    param(
        [string]$TrustedActivePython,
        [string]$ExplicitPython
    )

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPython)) {
        $resolvedExplicit = [IO.Path]::GetFullPath($ExplicitPython)
        if (-not (Test-Path -LiteralPath $resolvedExplicit -PathType Leaf)) {
            throw "No existe el Python 3.12 indicado en $resolvedExplicit"
        }
        & $resolvedExplicit -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "El runtime indicado no es Python 3.12: $resolvedExplicit"
        }
        return $resolvedExplicit
    }
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
    if (
        $TrustedActivePython -and
        (Test-Path -LiteralPath $TrustedActivePython -PathType Leaf)
    ) {
        & $TrustedActivePython -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [IO.Path]::GetFullPath($TrustedActivePython)
        }
    }
    throw 'Se requiere Python 3.12 en PATH, py.exe o el runtime 3.12 válido del release activo.'
}

function Get-TrustedActivePython {
    param([object]$State, [string]$Root)
    if (-not $State) { return $null }
    $version = [string]$State.active_version
    $activePath = [string]$State.active_path
    if (
        [string]::IsNullOrWhiteSpace($version) -or
        [string]::IsNullOrWhiteSpace($activePath)
    ) { return $null }
    try {
        $releasesRoot = [IO.Path]::GetFullPath((Join-Path $Root 'releases'))
        $expectedPath = [IO.Path]::GetFullPath((Join-Path $releasesRoot $version))
        $resolvedPath = [IO.Path]::GetFullPath($activePath)
        if (-not $resolvedPath.Equals($expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
            return $null
        }
        if (-not $resolvedPath.StartsWith($releasesRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            return $null
        }
        return (Join-Path $resolvedPath 'backend\venv\Scripts\python.exe')
    }
    catch { return $null }
}

function Wait-StationState {
    param(
        [bool]$Ready,
        [int]$TimeoutSeconds = 30,
        [string]$ExpectedVersion,
        [switch]$AllowMissingVersion
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/local/v1/health/ready" -TimeoutSec 2
            $responseVersion = $null
            if ($response.PSObject.Properties['app_version']) {
                $responseVersion = [string]$response.app_version
            }
            if (
                $Ready -and
                $response.status -eq 'READY' -and
                (
                    -not $ExpectedVersion -or
                    $responseVersion -eq $ExpectedVersion -or
                    (
                        $AllowMissingVersion -and
                        [string]::IsNullOrWhiteSpace($responseVersion)
                    )
                )
            ) { return $true }
        }
        catch {
            if (-not $Ready -and -not (Test-LoopbackPortOpen)) { return $true }
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function Wait-CentralOnline {
    param([string]$ExpectedVersion, [int]$TimeoutSeconds = 90)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/local/v1/health/ready" -TimeoutSec 2
            $responseVersion = $null
            if ($response.PSObject.Properties['app_version']) {
                $responseVersion = [string]$response.app_version
            }
            if (
                $response.status -eq 'READY' -and
                $responseVersion -eq $ExpectedVersion -and
                $null -ne $response.central -and
                $response.central.state -eq 'ONLINE'
            ) {
                return $true
            }
        }
        catch { }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function Stop-Release {
    param([string]$ReleasePath)
    if ([string]::IsNullOrWhiteSpace($ReleasePath)) {
        throw 'El estado activo no contiene una ruta de release válida; no es seguro abrir la base.'
    }
    $python = Join-Path $ReleasePath 'backend\venv\Scripts\python.exe'
    $control = Join-Path $ReleasePath 'backend\station_control.py'
    if (
        -not (Test-Path -LiteralPath $python -PathType Leaf) -or
        -not (Test-Path -LiteralPath $control -PathType Leaf)
    ) {
        throw "El release $ReleasePath no tiene runtime/control verificable; no se puede demostrar que la estación quedó detenida."
    }
    & $python $control stop --station-id $StationId | Out-Host
    if ($LASTEXITCODE -notin @(0, 4)) {
        throw "No se pudo detener ordenadamente la estacion (codigo $LASTEXITCODE)."
    }
    if (-not (Wait-StationState -Ready $false -TimeoutSeconds 20)) {
        throw 'La estacion no libero el puerto dentro del tiempo permitido.'
    }
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
        throw 'Falta el backup previo o la línea base posmigración; no se puede demostrar que el rollback conservará los hechos operativos.'
    }
    foreach ($candidate in @($BackupPath, $ValidationBaselinePath)) {
        $verifyOutput = Invoke-CheckedPython $Python @(
            $StorageScript, '--data-root', $DataRoot, '--station-id', $StationId,
            'verify', $candidate
        ) "El backup de rollback no es válido: $candidate"
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
        throw "Se detectaron pesajes, impresiones, correcciones o acuses posteriores a la actualización; no se restaurará un backup antiguo.`n$($comparisonOutput -join [Environment]::NewLine)"
    }
    $comparison = Get-LastJson $comparisonOutput
    if ([string]$comparison.event -ne 'OPERATIONAL_STATE_MATCH') {
        throw 'La comparación operacional no confirmó un estado idéntico a la línea base.'
    }
}

$PackagePath = [IO.Path]::GetFullPath($PackagePath)
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
if ($SkipRuntimeInstall -and -not $NoStart) {
    throw '-SkipRuntimeInstall solo se admite junto con -NoStart para pruebas controladas; nunca en una actualización productiva.'
}
if ($ResumeFirstActivation -and $NoStart) {
    throw '-ResumeFirstActivation exige completar el arranque, Central y la tarea; no se puede combinar con -NoStart.'
}
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

$statePath = Join-Path $DataRoot 'run\active-release.json'
$previousState = $null
if (Test-Path -LiteralPath $statePath) {
    $previousState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
}
$databasePath = Join-Path $DataRoot 'data\pesajes.db'
$databaseExists = Test-Path -LiteralPath $databasePath -PathType Leaf
if ($previousState -and -not $databaseExists) {
    throw 'El release activo no tiene ProgramData\data\pesajes.db. Detenerse y recuperar la base; no crear una SQLite vacía.'
}
if (-not $previousState -and $databaseExists -and -not $PreparedLegacyMigration) {
    throw 'ProgramData contiene pesajes.db sin active-release.json. Es una instalación parcial o ambigua; use el puente legacy o recuperación supervisada.'
}
if (-not $databaseExists -and -not $AllowEmptyStation) {
    throw 'No se encontró la base autoritativa. Para el piloto con historial use Migrate-LegacyStation.ps1; una estación limpia exige -AllowEmptyStation explícito.'
}

$trustedActivePython = Get-TrustedActivePython -State $previousState -Root $InstallRoot
$bootstrapPython = Find-BootstrapPython `
    -TrustedActivePython $trustedActivePython `
    -ExplicitPython $BootstrapPythonPath

$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$currentUserSid = Resolve-AccountSid $currentUser
$scheduledTaskCommand = Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue
if ($previousState -and $scheduledTaskCommand) {
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existingTask) {
        $taskUser = [string]$existingTask.Principal.UserId
        $taskUserSid = Resolve-AccountSid $taskUser
        if (-not $currentUserSid -or -not $taskUserSid) {
            throw 'No se pudo comprobar que la tarea programada y el token DPAPI usan la misma cuenta Windows.'
        }
        if ($currentUserSid -ne $taskUserSid) {
            throw "La tarea $TaskName usa $taskUser, pero la actualización se ejecuta como $currentUser. Provisionar y actualizar con la cuenta operativa."
        }
    }
}
if (-not $NoStart -and -not (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) {
    throw 'Windows no expone Register-ScheduledTask; no se puede garantizar el arranque persistente del piloto.'
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

$resumingFirstActivation = $false
if ($ResumeFirstActivation) {
    if (-not $previousState) {
        throw 'No existe una primera activación pendiente que pueda reanudarse.'
    }
    $hasPreviousRelease = (
        $previousState.PSObject.Properties['previous_version'] -and
        -not [string]::IsNullOrWhiteSpace([string]$previousState.previous_version)
    )
    $hasBaseline = (
        $previousState.PSObject.Properties['validation_baseline'] -and
        -not [string]::IsNullOrWhiteSpace([string]$previousState.validation_baseline)
    )
    $hasPreupdateBackup = (
        $previousState.PSObject.Properties['preupdate_backup'] -and
        -not [string]::IsNullOrWhiteSpace([string]$previousState.preupdate_backup)
    )
    if (
        ([string]$previousState.active_version) -ne $version -or
        $hasPreviousRelease -or
        -not $hasBaseline -or
        -not $hasPreupdateBackup -or
        -not ([IO.Path]::GetFullPath([string]$previousState.active_path)).Equals(
            [IO.Path]::GetFullPath($releasePath),
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw '-ResumeFirstActivation solo admite el mismo paquete de una primera activación incompleta, sin release anterior y con sus dos backups registrados.'
    }
    $resumingFirstActivation = $true
}
elseif ($previousState -and ([string]$previousState.active_version) -eq $version) {
    throw "La versión $version ya está activa. Use una versión nueva e inmutable; no se admite actualizar sobre el mismo release."
}

if (-not $SkipRuntimeInstall) {
    if (-not (Test-Path -LiteralPath $newPython -PathType Leaf)) {
        & $bootstrapPython -m venv (Join-Path $releasePath 'backend\venv')
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno Python del nuevo release.' }
    }
    if (-not (Test-Path -LiteralPath $newPython -PathType Leaf)) {
        throw 'El nuevo release no contiene un runtime Python utilizable.'
    }
    $runtimeLock = Join-Path $releasePath 'backend\requirements-runtime.lock'
    $wheelhouse = Join-Path $releasePath 'wheels'
    & $newPython -m pip install --no-index --find-links $wheelhouse --requirement $runtimeLock
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias offline.' }
    & $newPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'El runtime instalado tiene dependencias incompatibles.' }
}
elseif ($databaseExists -and -not (Test-Path -LiteralPath $newPython -PathType Leaf)) {
    throw '-SkipRuntimeInstall no puede omitir el runtime cuando existe una base autoritativa que debe respaldarse y migrarse.'
}

$previousPath = if ($previousState) { [string]$previousState.active_path } else { $null }
if ($previousPath) { Stop-Release $previousPath }
if (Test-LoopbackPortOpen) {
    throw "El puerto $Port continúa ocupado. No se creará backup ni se migrará la base mientras exista un proceso activo."
}

$backupPath = if ($resumingFirstActivation) { [string]$previousState.preupdate_backup } else { $null }
$validationBaselinePath = if ($resumingFirstActivation) { [string]$previousState.validation_baseline } else { $null }
$activated = $false
$authoritativeMigrationStarted = $false
$pilotPreflight = $null
try {
    # El backup autoritativo se toma con la estación ya detenida. Así ninguna
    # captura o impresión puede quedar entre el punto de recuperación y el
    # cambio de release.
    $backupPython = $newPython
    $backupStorage = Join-Path $releasePath 'backend\station_storage.py'
    if ($previousState) {
        $candidate = Join-Path ([string]$previousState.active_path) 'backend\venv\Scripts\python.exe'
        $candidateStorage = Join-Path ([string]$previousState.active_path) 'backend\station_storage.py'
        if (
            (Test-Path -LiteralPath $candidate -PathType Leaf) -and
            (Test-Path -LiteralPath $candidateStorage -PathType Leaf)
        ) {
            $backupPython = $candidate
            $backupStorage = $candidateStorage
        }
    }

    if (-not $resumingFirstActivation -and (Test-Path -LiteralPath $databasePath)) {
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

        # La migración autoritativa también ocurre con la estación detenida.
        # Después se crea una línea base verificable con el mismo esquema que
        # usará el release nuevo; cualquier operación posterior será detectable.
        $authoritativeMigrationStarted = $true
        Invoke-CheckedPython $newPython @(
            (Join-Path $releasePath 'backend\station_storage.py'),
            '--data-root', $DataRoot, '--station-id', $StationId, 'migrate'
        ) 'La migración autoritativa falló antes de activar el nuevo release' | Out-Null
        $validationOutput = Invoke-CheckedPython $newPython @(
            (Join-Path $releasePath 'backend\station_storage.py'),
            '--data-root', $DataRoot, '--station-id', $StationId,
            'backup', '--reason', "pre-validation-$version"
        ) 'No se pudo crear la línea base posmigración para un rollback seguro'
        $validationResult = Get-LastJson $validationOutput
        $validationBaselinePath = [string]$validationResult.backup.path
    }

    if (-not $NoStart) {
        $pilotPreflightOutput = Invoke-CheckedPython $newPython @(
            (Join-Path $releasePath 'backend\station_control.py'),
            'validate-pilot-config', '--data-root', $DataRoot
        ) 'La configuracion central minima del piloto es invalida'
        $pilotPreflight = Get-LastJson $pilotPreflightOutput
        if (-not [bool]$pilotPreflight.valid) {
            throw 'La configuracion central minima del piloto es invalida.'
        }
    }

    if ($resumingFirstActivation) {
        Write-Output "FIRST_ACTIVATION_RESUMED version=$version"
    }
    else {
        $activateArguments = @(
            $managerScript, 'activate', '--version', $version,
            '--install-root', $InstallRoot, '--data-root', $DataRoot
        )
        if ($backupPath) {
            $activateArguments += @('--preupdate-backup', ([string]$backupPath))
        }
        if ($validationBaselinePath) {
            $activateArguments += @('--validation-baseline', ([string]$validationBaselinePath))
        }
        $activateOutput = Invoke-CheckedPython $bootstrapPython $activateArguments `
            'No se pudo activar el nuevo release'
        $activateOutput | Out-Host
    }
    $activated = $true

    if ($NoStart) {
        Write-Output "UPDATE_STAGED version=$version start=deferred"
        exit 0
    }

    & (Join-Path $releasePath 'release\Start-ActiveStation.ps1') -InstallRoot $InstallRoot -DataRoot $DataRoot -StationId $StationId -Port $Port
    if (-not (Wait-StationState -Ready $true -TimeoutSeconds 45 -ExpectedVersion $version)) {
        throw 'El nuevo release no alcanzo readiness.'
    }
    Write-Output "PILOT_CONFIG_READY station_id=$($pilotPreflight.station_id) operator_id=$($pilotPreflight.scm_operator_id)"
    if (-not (Wait-CentralOnline -ExpectedVersion $version -TimeoutSeconds 90)) {
        throw 'Central no confirmo estado ONLINE para este arranque dentro del tiempo permitido.'
    }
    Write-Output "CENTRAL_ONLINE station_id=$($pilotPreflight.station_id)"
    $launcherRoot = Join-Path $InstallRoot 'launcher'
    New-Item -ItemType Directory -Path $launcherRoot -Force | Out-Null
    @(
        'Inspect-Station.ps1',
        'Install-StationTask.ps1',
        'Rollback-Station.ps1',
        'Start-ActiveStation.ps1',
        'Update-Station.ps1'
    ) | ForEach-Object {
        Copy-Item -LiteralPath (Join-Path $releasePath "release\$_") -Destination (Join-Path $launcherRoot $_) -Force
    }
    & (Join-Path $launcherRoot 'Install-StationTask.ps1') `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -StationId $StationId `
        -Port $Port `
        -TaskName $TaskName `
        -RunAsUser $currentUser
    Write-Output "STATION_TASK_READY task=$TaskName user=$currentUser"
    Write-Output "UPDATE_COMPLETE version=$version backup=$backupPath resumed=$resumingFirstActivation"
}
catch {
    $updateError = $_
    if ($activated) { Stop-Release $releasePath }
    if ($resumingFirstActivation) {
        throw "La reanudación todavía no completó Central/tarea. El mismo release y sus datos quedaron activos pero detenidos; corrija la causa y repita con -ResumeFirstActivation. Error: $updateError"
    }
    if (-not $previousState) {
        if ($activated) {
            throw "La primera activación quedó detenida después de crear su puntero. No se perdió la base importada: corrija la causa y ejecute Update-Station.ps1 con el mismo paquete y -ResumeFirstActivation. Error: $updateError"
        }
        if ($backupPath -and $authoritativeMigrationStarted -and -not $activated) {
            Invoke-CheckedPython $backupPython @(
                $backupStorage,
                '--data-root', $DataRoot, '--station-id', $StationId,
                'restore', $backupPath
            ) 'La primera instalación falló y tampoco se pudo restaurar su base previa' | Out-Null
        }
        throw "La primera instalacion fallo y no existe un release anterior: $updateError"
    }
    if ($activated) {
        try {
            Assert-RollbackEvidence `
                -Python $newPython `
                -StorageScript (Join-Path $releasePath 'backend\station_storage.py') `
                -BackupPath $backupPath `
                -ValidationBaselinePath $validationBaselinePath
        }
        catch {
            throw "La actualización falló, pero el rollback automático fue cancelado para no perder datos. El release nuevo quedó detenido para conciliación manual. Error inicial: $updateError. Evidencia: $_"
        }
        Invoke-CheckedPython $bootstrapPython @(
            $managerScript, 'rollback', '--install-root', $InstallRoot, '--data-root', $DataRoot
        ) 'No se pudo restaurar el puntero del release anterior' | Out-Host
        try {
            Assert-RollbackEvidence `
                -Python $newPython `
                -StorageScript (Join-Path $releasePath 'backend\station_storage.py') `
                -BackupPath $backupPath `
                -ValidationBaselinePath $validationBaselinePath
        }
        catch {
            Invoke-CheckedPython $bootstrapPython @(
                $managerScript, 'rollback', '--install-root', $InstallRoot, '--data-root', $DataRoot
            ) 'Cambió la base durante el rollback y no se pudo recuperar el puntero del release nuevo' | Out-Null
            throw "La base cambió después de mover el puntero. Se recuperó el release nuevo y no se restauró ningún backup. Evidencia: $_"
        }
        if ($backupPath) {
            $previousPython = Join-Path $previousPath 'backend\venv\Scripts\python.exe'
            Invoke-CheckedPython $previousPython @(
                (Join-Path $previousPath 'backend\station_storage.py'),
                '--data-root', $DataRoot, '--station-id', $StationId,
                'restore', $backupPath
            ) 'No se pudo restaurar la base previa a la actualizacion' | Out-Host
        }
    }
    elseif ($backupPath -and $authoritativeMigrationStarted) {
        Invoke-CheckedPython $backupPython @(
            $backupStorage,
            '--data-root', $DataRoot, '--station-id', $StationId,
            'restore', $backupPath
        ) 'La actualización falló antes de activar y no se pudo restaurar la base previa' | Out-Host
    }
    & (Join-Path $previousPath 'release\Start-ActiveStation.ps1') -InstallRoot $InstallRoot -DataRoot $DataRoot -StationId $StationId -Port $Port
    if (-not (Wait-StationState -Ready $true -TimeoutSeconds 45 -ExpectedVersion ([string]$previousState.active_version) -AllowMissingVersion)) {
        throw "Fallo el release nuevo y el anterior no recupero readiness. Error inicial: $updateError"
    }
    throw "La actualizacion fue revertida; la version anterior esta operativa. Error: $updateError"
}
