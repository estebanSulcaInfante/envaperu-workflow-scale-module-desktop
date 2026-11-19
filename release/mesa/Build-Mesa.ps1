[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$Python = (Resolve-Path -LiteralPath $Python).Path
& $Python -c 'import win32print, serial, waitress'
if ($LASTEXITCODE -ne 0) { throw 'Faltan dependencias de la estacion para Windows (pywin32, pyserial o waitress).' }
$module = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$output = (New-Item -ItemType Directory -Force -Path $OutputDirectory).FullName
$work = (New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) ('mesa-build-' + [guid]::NewGuid()))).FullName
$frontend = Join-Path $module 'frontend'
$ui = Join-Path $work 'mesa-frontend'
Push-Location $frontend
try {
    & node node_modules/vite/bin/vite.js build --config vite.mesa.config.js --outDir $ui
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo construir la interfaz de mesa.' }
} finally { Pop-Location }
$entry = Join-Path $module 'backend\run_mesa_pilot.py'
& $Python -m PyInstaller --noconfirm --onefile --console --noupx --name MesaPesaje --log-level WARN --specpath $work --workpath (Join-Path $work 'build') --distpath (Join-Path $work 'dist') --add-data "${ui}:build/mesa-frontend" $entry
if ($LASTEXITCODE -ne 0) { throw 'No se pudo construir MesaPesaje.exe.' }
$dist = Join-Path $work 'dist'
$files = [ordered]@{}
foreach ($name in @('Instalar Mesa.cmd', 'Mesa.ps1', 'LEEME.txt')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $dist
}
foreach ($name in @('MesaPesaje.exe', 'Mesa.ps1', 'LEEME.txt')) {
    $files[$name] = (Get-FileHash -LiteralPath (Join-Path $dist $name)).Hash
}
$files | ConvertTo-Json | Set-Content -Encoding ASCII -LiteralPath (Join-Path $dist 'paquete.json')
$archive = Join-Path $output 'MesaPesaje-Accura-piloto-win-x64.zip'
$staged = Join-Path $output (('mesa-' + [guid]::NewGuid()) + '.zip')
Compress-Archive -Path (Join-Path $dist '*') -DestinationPath $staged
Move-Item -LiteralPath $staged -Destination $archive -Force
Get-FileHash -LiteralPath $archive
