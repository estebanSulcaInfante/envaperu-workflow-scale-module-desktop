param(
    [string]$InstallRoot = "$env:ProgramFiles\EnvaPeru\Pesaje",
    [string]$DataRoot = "$env:ProgramData\EnvaPeru\Pesaje",
    [string]$LegacyRoot,
    [string]$LegacyDatabasePath,
    [int]$Port = 5050,
    [string]$TaskName = 'EnvaPeru Pesaje Edge',
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Read-EnvironmentFile {
    param([string]$Path)
    $values = [ordered]@{}
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

function Get-SafeConfiguration {
    param([hashtable]$Values)
    $allowed = @(
        'STATION_CODE',
        'STATION_UUID',
        'STATION_MODE',
        'SCALE_PORT',
        'SCALE_BAUD_RATE',
        'PRINTER_TYPE',
        'PRINTER_NAME',
        'PRINTER_PORT',
        'API_PORT',
        'CENTRAL_ORIGIN',
        'ALLOW_INSECURE_CENTRAL',
        'MONITORING_ENABLED',
        'SYNC_ENABLED',
        'PORTFOLIO_DEMO_MODE',
        'ALLOW_SCALE_SIMULATION',
        'ALLOW_LOCAL_SCM_DEMO',
        'SIMULATE_PRINTER',
        'SCM_OPERATOR_ID'
    )
    $safe = [ordered]@{}
    foreach ($name in $allowed) {
        if ($Values.Contains($name)) {
            $safe[$name] = [string]$Values[$name]
        }
    }
    return $safe
}

function Get-HealthObservation {
    param([string]$Endpoint)
    try {
        $response = Invoke-RestMethod -Uri $Endpoint -TimeoutSec 2
        return [ordered]@{
            reachable = $true
            status = [string]$response.status
        }
    }
    catch {
        return [ordered]@{
            reachable = $false
            status = $null
        }
    }
}

function Test-LoopbackPortOpen {
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

function Get-Sha256 {
    param([string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $algorithm.ComputeHash($stream)
        return ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}

function Get-DatabaseObservation {
    param([string]$Path, [bool]$CanHash)
    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        return [ordered]@{
            path = $fullPath
            exists = $false
        }
    }

    $item = Get-Item -LiteralPath $fullPath
    $walPath = "$fullPath-wal"
    $shmPath = "$fullPath-shm"
    $wal = $null
    $shm = $null
    if (Test-Path -LiteralPath $walPath -PathType Leaf) {
        $walItem = Get-Item -LiteralPath $walPath
        $wal = [ordered]@{
            path = $walItem.FullName
            size_bytes = [long]$walItem.Length
            last_write_utc = $walItem.LastWriteTimeUtc.ToString('o')
        }
    }
    if (Test-Path -LiteralPath $shmPath -PathType Leaf) {
        $shmItem = Get-Item -LiteralPath $shmPath
        $shm = [ordered]@{
            path = $shmItem.FullName
            size_bytes = [long]$shmItem.Length
            last_write_utc = $shmItem.LastWriteTimeUtc.ToString('o')
        }
    }

    $sha256 = $null
    if ($CanHash -and $null -eq $wal) {
        $sha256 = Get-Sha256 $fullPath
    }
    return [ordered]@{
        path = $item.FullName
        exists = $true
        size_bytes = [long]$item.Length
        last_write_utc = $item.LastWriteTimeUtc.ToString('o')
        sha256 = $sha256
        sha256_deferred = ($null -eq $sha256)
        wal = $wal
        shm = $shm
    }
}

$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
if ($LegacyRoot) { $LegacyRoot = [IO.Path]::GetFullPath($LegacyRoot) }
if ($LegacyDatabasePath) {
    $LegacyDatabasePath = [IO.Path]::GetFullPath($LegacyDatabasePath)
}

$listeners = @()
$listenerProbeReliable = $true
try {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | ForEach-Object {
        [ordered]@{
            local_address = [string]$_.LocalAddress
            local_port = [int]$_.LocalPort
            process_id = [int]$_.OwningProcess
        }
    })
}
catch {
    $listeners = @()
    $netstatLines = @(netstat -ano -p tcp 2>$null)
    if ($LASTEXITCODE -ne 0) {
        $listenerProbeReliable = $false
    }
    else {
        # El estado de netstat puede estar localizado. Cualquier fila cuyo
        # endpoint local use el puerto significa que todavía no está libre.
        $pattern = "^\s*TCP\s+(\S+):$Port\s+\S+\s+\S+\s+(\d+)\s*$"
        foreach ($line in $netstatLines) {
            if ($line -match $pattern) {
                $listeners += [ordered]@{
                    local_address = [string]$Matches[1]
                    local_port = $Port
                    process_id = [int]$Matches[2]
                }
            }
        }
    }
}
$live = Get-HealthObservation "http://127.0.0.1:$Port/api/local/v1/health/live"
$ready = Get-HealthObservation "http://127.0.0.1:$Port/api/local/v1/health/ready"
$portProbeOpen = $listeners.Count -gt 0
if (-not $listenerProbeReliable) { $portProbeOpen = Test-LoopbackPortOpen }
$isListening = (
    $listeners.Count -gt 0 -or
    $portProbeOpen -or
    [bool]$live.reachable -or
    [bool]$ready.reachable
)

$statePath = Join-Path $DataRoot 'run\active-release.json'
$activeState = $null
$activeManifest = $null
$stateError = $null
if (Test-Path -LiteralPath $statePath -PathType Leaf) {
    try {
        $activeState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $manifestPath = Join-Path ([string]$activeState.active_path) 'manifest.json'
        if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
            $activeManifest = [ordered]@{
                app_version = [string]$manifest.app_version
                source_revision = [string]$manifest.source_revision
                created_at_utc = [string]$manifest.created_at_utc
            }
        }
    }
    catch {
        $stateError = $_.Exception.Message
    }
}

$versionedEnvironmentPath = Join-Path $DataRoot 'config\station.env'
$legacyEnvironmentPath = $null
if ($LegacyRoot) { $legacyEnvironmentPath = Join-Path $LegacyRoot '.env' }
$configurationPath = $null
if (Test-Path -LiteralPath $versionedEnvironmentPath -PathType Leaf) {
    $configurationPath = $versionedEnvironmentPath
}
elseif ($legacyEnvironmentPath -and (Test-Path -LiteralPath $legacyEnvironmentPath -PathType Leaf)) {
    $configurationPath = $legacyEnvironmentPath
}
$rawConfiguration = Read-EnvironmentFile $configurationPath
$safeConfiguration = Get-SafeConfiguration $rawConfiguration

$databasePaths = New-Object System.Collections.ArrayList
$versionedDatabase = Join-Path $DataRoot 'data\pesajes.db'
if (Test-Path -LiteralPath $versionedDatabase -PathType Leaf) {
    [void]$databasePaths.Add([IO.Path]::GetFullPath($versionedDatabase))
}
if ($LegacyDatabasePath) {
    if (-not $databasePaths.Contains($LegacyDatabasePath)) {
        [void]$databasePaths.Add($LegacyDatabasePath)
    }
}
elseif ($LegacyRoot) {
    $defaultLegacyDatabase = [IO.Path]::GetFullPath(
        (Join-Path $LegacyRoot 'backend\instance\pesajes.db')
    )
    if (-not $databasePaths.Contains($defaultLegacyDatabase)) {
        [void]$databasePaths.Add($defaultLegacyDatabase)
    }
}

$databaseObservations = @($databasePaths | ForEach-Object {
    Get-DatabaseObservation -Path ([string]$_) -CanHash (-not $isListening)
})
$existingDatabases = @($databaseObservations | Where-Object { $_.exists })

$legacyGit = $null
if ($LegacyRoot -and (Test-Path -LiteralPath (Join-Path $LegacyRoot '.git'))) {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        $head = @(& $git.Source -C $LegacyRoot rev-parse HEAD 2>$null)
        $status = @(& $git.Source -C $LegacyRoot status --short 2>$null)
        if ($LASTEXITCODE -eq 0 -and $head.Count -gt 0) {
            $legacyGit = [ordered]@{
                head = [string]$head[-1]
                dirty = ($status.Count -gt 0)
                changed_paths = @($status)
            }
        }
    }
}

$tokenPath = Join-Path $DataRoot 'secrets\station-token.dpapi'
$tokenPresent = $false
if (Test-Path -LiteralPath $tokenPath -PathType Leaf) {
    $tokenPresent = (Get-Item -LiteralPath $tokenPath).Length -gt 0
}

$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$currentUserSid = Resolve-AccountSid $currentUser
$taskPrincipal = $null
$taskPrincipalSid = $null
$taskUsesCurrentUser = $null
try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $taskPrincipal = [string]$task.Principal.UserId
    $taskPrincipalSid = Resolve-AccountSid $taskPrincipal
    if ($currentUserSid -and $taskPrincipalSid) {
        $taskUsesCurrentUser = $currentUserSid -eq $taskPrincipalSid
    }
}
catch { }

$pilotValidation = $null
$tokenDecryptable = $null
if ($null -ne $activeState -and $null -eq $stateError) {
    $activePython = Join-Path ([string]$activeState.active_path) 'backend\venv\Scripts\python.exe'
    $activeControl = Join-Path ([string]$activeState.active_path) 'backend\station_control.py'
    if (
        (Test-Path -LiteralPath $activePython -PathType Leaf) -and
        (Test-Path -LiteralPath $activeControl -PathType Leaf)
    ) {
        $validationOutput = @(& $activePython $activeControl `
            validate-pilot-config --data-root $DataRoot 2>$null)
        $reversedValidation = @($validationOutput)
        [array]::Reverse($reversedValidation)
        foreach ($line in $reversedValidation) {
            try {
                $pilotValidation = $line.ToString() | ConvertFrom-Json
                break
            }
            catch { }
        }
        if ($null -ne $pilotValidation) {
            $tokenDecryptable = (
                $null -ne $pilotValidation.PSObject.Properties['token_storage'] -and
                [string]$pilotValidation.token_storage -eq 'DPAPI'
            )
        }
    }
}

$versionedDatabaseExists = Test-Path -LiteralPath $versionedDatabase -PathType Leaf
$legacyDatabaseExists = $false
if ($LegacyDatabasePath) {
    $legacyDatabaseExists = Test-Path -LiteralPath $LegacyDatabasePath -PathType Leaf
}
elseif ($LegacyRoot) {
    $legacyDatabaseExists = Test-Path -LiteralPath $defaultLegacyDatabase -PathType Leaf
}

$installationKind = 'UNKNOWN'
if ($null -ne $activeState -and $null -eq $stateError) {
    $installationKind = 'VERSIONED'
}
elseif ($versionedDatabaseExists -and $legacyDatabaseExists) {
    $installationKind = 'CONFLICT'
}
elseif ($versionedDatabaseExists) {
    $installationKind = 'PARTIAL_VERSIONED'
}
elseif ($legacyDatabaseExists) {
    $installationKind = 'LEGACY'
}

$findings = New-Object System.Collections.ArrayList
if ($isListening) {
    [void]$findings.Add('PORT_ACTIVE_STOP_STATION_BEFORE_UPDATE')
}
if ($stateError) {
    [void]$findings.Add('ACTIVE_RELEASE_STATE_INVALID')
}
if ($existingDatabases.Count -eq 0) {
    [void]$findings.Add('DATABASE_NOT_FOUND')
}
if ($installationKind -eq 'CONFLICT') {
    [void]$findings.Add('MULTIPLE_DATABASES_REQUIRE_EXPLICIT_SELECTION')
}
if ($installationKind -eq 'PARTIAL_VERSIONED') {
    [void]$findings.Add('PARTIAL_VERSIONED_INSTALLATION_REQUIRES_RECOVERY')
}
if ($installationKind -eq 'VERSIONED' -and $legacyDatabaseExists) {
    [void]$findings.Add('LEGACY_DATABASE_PRESENT_DO_NOT_REIMPORT')
}
foreach ($flag in @('PORTFOLIO_DEMO_MODE', 'ALLOW_SCALE_SIMULATION', 'ALLOW_LOCAL_SCM_DEMO', 'SIMULATE_PRINTER')) {
    if ($safeConfiguration.Contains($flag) -and [string]$safeConfiguration[$flag] -match '^(?i:true|1|yes)$') {
        [void]$findings.Add("$flag`_MUST_BE_FALSE_FOR_PHYSICAL_PILOT")
    }
}
if (-not $safeConfiguration.Contains('CENTRAL_ORIGIN')) {
    [void]$findings.Add('CENTRAL_ORIGIN_NOT_CONFIGURED')
}
if (-not $safeConfiguration.Contains('SCM_OPERATOR_ID')) {
    [void]$findings.Add('SCM_OPERATOR_ID_NOT_CONFIGURED')
}
if (-not $safeConfiguration.Contains('STATION_UUID')) {
    [void]$findings.Add('STATION_UUID_NOT_CONFIGURED')
}
if (-not $tokenPresent) {
    [void]$findings.Add('CENTRAL_TOKEN_NOT_PROVISIONED')
}
if ($tokenPresent -and $installationKind -eq 'VERSIONED' -and $tokenDecryptable -ne $true) {
    [void]$findings.Add('CENTRAL_TOKEN_NOT_DECRYPTABLE_BY_CURRENT_USER')
}
if ($taskUsesCurrentUser -eq $false) {
    [void]$findings.Add('SCHEDULED_TASK_USER_DIFFERS_FROM_CURRENT_USER')
}

$operatorReady = $false
if ($safeConfiguration.Contains('SCM_OPERATOR_ID')) {
    $operatorValue = 0
    $operatorReady = [int]::TryParse(
        [string]$safeConfiguration['SCM_OPERATOR_ID'],
        [ref]$operatorValue
    ) -and $operatorValue -gt 0
    if (-not $operatorReady) {
        [void]$findings.Add('SCM_OPERATOR_ID_INVALID')
    }
}
$originReady = (
    $safeConfiguration.Contains('CENTRAL_ORIGIN') -and
    [string]$safeConfiguration['CENTRAL_ORIGIN'] -match '^https://'
)
$uuidReady = $false
if ($safeConfiguration.Contains('STATION_UUID')) {
    $stationGuid = [Guid]::Empty
    $uuidReady = [Guid]::TryParse(
        [string]$safeConfiguration['STATION_UUID'],
        [ref]$stationGuid
    )
    if (-not $uuidReady) {
        [void]$findings.Add('STATION_UUID_INVALID')
    }
}
$stationModeReady = (
    -not $safeConfiguration.Contains('STATION_MODE') -or
    [string]$safeConfiguration['STATION_MODE'] -eq 'MONITORED_LEGACY'
)
if (-not $stationModeReady) {
    [void]$findings.Add('STATION_MODE_INVALID')
}
$secureCentralReady = (
    -not $safeConfiguration.Contains('ALLOW_INSECURE_CENTRAL') -or
    [string]$safeConfiguration['ALLOW_INSECURE_CENTRAL'] -notmatch '^(?i:true|1|yes)$'
)
if (-not $secureCentralReady) {
    [void]$findings.Add('ALLOW_INSECURE_CENTRAL_MUST_BE_FALSE')
}
$physicalModeReady = $true
foreach ($flag in @('PORTFOLIO_DEMO_MODE', 'ALLOW_SCALE_SIMULATION', 'ALLOW_LOCAL_SCM_DEMO', 'SIMULATE_PRINTER')) {
    if ($safeConfiguration.Contains($flag) -and [string]$safeConfiguration[$flag] -match '^(?i:true|1|yes)$') {
        $physicalModeReady = $false
    }
}
$tokenReady = $tokenPresent
if ($installationKind -eq 'VERSIONED') { $tokenReady = $tokenDecryptable -eq $true }
$pilotConfigReady = (
    $operatorReady -and $originReady -and $uuidReady -and
    $tokenReady -and $physicalModeReady -and $stationModeReady -and
    $secureCentralReady
)
$mechanicallyStopped = (
    -not $isListening -and
    -not [bool]$live.reachable -and
    -not [bool]$ready.reachable -and
    -not $stateError
)
$readyForVersionedUpdate = (
    $installationKind -eq 'VERSIONED' -and
    $mechanicallyStopped -and
    $versionedDatabaseExists -and
    $pilotConfigReady
)
$readyForLegacyBridge = (
    $installationKind -eq 'LEGACY' -and
    $mechanicallyStopped -and
    $existingDatabases.Count -eq 1
)

$report = [ordered]@{
    event = 'STATION_UPGRADE_INSPECTION'
    checked_at_utc = [DateTime]::UtcNow.ToString('o')
    computer_name = [Environment]::MachineName
    installation_kind = $installationKind
    install_root = $InstallRoot
    data_root = $DataRoot
    runtime = [ordered]@{
        port = $Port
        listening = $isListening
        port_probe_open = $portProbeOpen
        listener_probe_reliable = $listenerProbeReliable
        listeners = @($listeners)
        live = $live
        ready = $ready
    }
    active_release = [ordered]@{
        state_path = $statePath
        state = $activeState
        manifest = $activeManifest
        error = $stateError
    }
    legacy = [ordered]@{
        root = $LegacyRoot
        git = $legacyGit
    }
    configuration = [ordered]@{
        source_path = $configurationPath
        safe_values = $safeConfiguration
        token_path = $tokenPath
        token_present = $tokenPresent
        token_decryptable_current_user = $tokenDecryptable
        pilot_validation = $pilotValidation
        secrets_exposed = $false
    }
    windows_identity = [ordered]@{
        current_user = $currentUser
        current_user_sid = $currentUserSid
        task_name = $TaskName
        task_principal = $taskPrincipal
        task_principal_sid = $taskPrincipalSid
        task_uses_current_user = $taskUsesCurrentUser
    }
    databases = @($databaseObservations)
    findings = @($findings)
    pilot_config_ready = $pilotConfigReady
    ready_for_versioned_update = $readyForVersionedUpdate
    ready_for_legacy_bridge = $readyForLegacyBridge
    # El puente legacy es una conversión distinta; nunca se presenta como una
    # actualización versionada lista para ejecutar.
    ready_for_update = $readyForVersionedUpdate
}

$json = $report | ConvertTo-Json -Depth 10
if ($OutputPath) {
    $resolvedOutput = [IO.Path]::GetFullPath($OutputPath)
    $parent = Split-Path -Parent $resolvedOutput
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    Set-Content -LiteralPath $resolvedOutput -Value $json -Encoding UTF8
}
Write-Output $json
