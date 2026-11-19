param([string]$C66Host)
$ErrorActionPreference = 'Stop'
$backend = Join-Path $PSScriptRoot 'backend'
$frontend = Join-Path $PSScriptRoot 'frontend'
$runtime = @('.venv', 'venv') |
    ForEach-Object { Join-Path $backend "$_/Scripts/python.exe" } |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
if (-not $runtime) { throw 'Instale el entorno Python del módulo de pesaje antes de iniciar la estación.' }

Push-Location $frontend
try {
    & node node_modules/vite/bin/vite.js build --config vite.mesa.config.js
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo construir la vista de retornos.' }
} finally {
    Pop-Location
}

Write-Host 'Estación local de retornos de Armado: http://127.0.0.1:5196/'
$pilotArgs = @((Join-Path $backend 'run_mesa_pilot.py'))
if ($C66Host) { $pilotArgs += @('--c66-host', $C66Host) }
& $runtime @pilotArgs
exit $LASTEXITCODE
