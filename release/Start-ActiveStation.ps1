param(
    [string]$InstallRoot = "$env:ProgramFiles\EnvaPeru\Pesaje",
    [string]$DataRoot = "$env:ProgramData\EnvaPeru\Pesaje",
    [string]$StationId = 'PESAJE-PLANTA-01',
    [int]$Port = 5050,
    [switch]$OpenBrowser,
    [switch]$Foreground
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Import-StationEnvironment {
    param([string]$EnvironmentFile)
    if (-not (Test-Path -LiteralPath $EnvironmentFile)) { return }
    Get-Content -LiteralPath $EnvironmentFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) { return }
        $name, $value = $line.Split('=', 2)
        if ($name -match '^[A-Za-z_][A-Za-z0-9_]*$') {
            [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
}

$statePath = Join-Path $DataRoot 'run\active-release.json'
if (-not (Test-Path -LiteralPath $statePath)) {
    throw "No existe un release activo en $statePath"
}
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$releasePath = [IO.Path]::GetFullPath([string]$state.active_path)
$releasesRoot = [IO.Path]::GetFullPath((Join-Path $InstallRoot 'releases'))
if (-not $releasePath.StartsWith($releasesRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'El release activo esta fuera del directorio de instalacion.'
}
$python = Join-Path $releasePath 'backend\venv\Scripts\python.exe'
$stationMain = Join-Path $releasePath 'backend\station_main.py'
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $stationMain)) {
    throw "El release activo $($state.active_version) no tiene un runtime completo."
}

Import-StationEnvironment (Join-Path $DataRoot 'config\station.env')
$env:STATION_DATA_ROOT = [IO.Path]::GetFullPath($DataRoot)
$env:STATION_APP_VERSION = [string]$state.active_version
$arguments = @($stationMain, '--station-id', $StationId, '--port', "$Port")
if ($OpenBrowser) { $arguments += '--open-browser' }

if ($Foreground) {
    & $python @arguments
    exit $LASTEXITCODE
}

$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $releasePath -WindowStyle Hidden -PassThru
Write-Output "STATION_START_REQUESTED version=$($state.active_version) pid=$($process.Id) port=$Port"
