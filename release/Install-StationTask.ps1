param(
    [string]$InstallRoot = "$env:ProgramFiles\EnvaPeru\Pesaje",
    [string]$DataRoot = "$env:ProgramData\EnvaPeru\Pesaje",
    [string]$StationId = 'PESAJE-PLANTA-01',
    [int]$Port = 5050,
    [string]$TaskName = 'EnvaPeru Pesaje Edge',
    [string]$RunAsUser = "$env:USERDOMAIN\$env:USERNAME"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$launcher = [IO.Path]::GetFullPath((Join-Path $InstallRoot 'launcher\Start-ActiveStation.ps1'))
if (-not (Test-Path -LiteralPath $launcher)) {
    throw "No existe el launcher estable en $launcher. Complete primero una instalacion versionada."
}

$arguments = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', ('"{0}"' -f $launcher),
    '-InstallRoot', ('"{0}"' -f ([IO.Path]::GetFullPath($InstallRoot))),
    '-DataRoot', ('"{0}"' -f ([IO.Path]::GetFullPath($DataRoot))),
    '-StationId', ('"{0}"' -f $StationId),
    '-Port', "$Port"
) -join ' '

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $RunAsUser
$principal = New-ScheduledTaskPrincipal -UserId $RunAsUser -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Inicia el launcher estable de la estacion edge EnvaPeru.' `
    -Force | Out-Null

Write-Output "STATION_TASK_INSTALLED task=$TaskName user=$RunAsUser"
