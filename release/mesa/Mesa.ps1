[CmdletBinding()]
param(
    [ValidateSet('Instalar','Iniciar','Configurar')]
    [string]$Accion = 'Iniciar',
    [string]$Directorio = (Join-Path $env:LOCALAPPDATA 'EnvaPeru\MesaPesajePiloto'),
    [string]$Escritorio = [Environment]::GetFolderPath('DesktopDirectory'),
    [switch]$SinPausa,
    [switch]$Central
)
$ErrorActionPreference = 'Stop'
trap {
    [Console]::Error.WriteLine($_.Exception.Message)
    if ($Accion -ne 'Instalar' -and -not [Console]::IsInputRedirected) {
        Read-Host 'Pulse Enter para cerrar' | Out-Null
    }
    exit 1
}
$configPath = Join-Path $Directorio 'conexion.json'
$dbPath = Join-Path $Directorio 'datos\mesa-piloto.sqlite3'
$exeName = 'MesaPesaje.exe'

function Get-MesaSha([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') }
    finally { $stream.Dispose(); $sha.Dispose() }
}

function Set-Conexion {
    $ports = [System.IO.Ports.SerialPort]::GetPortNames()
    Write-Host ("Puertos de Windows: " + ($ports -join ', '))
    $port = (Read-Host 'Puerto COM de la Accura (ver Administrador de dispositivos)').Trim().ToUpperInvariant()
    if ($port -notmatch '^COM[1-9][0-9]{0,3}$') { throw 'Indique un puerto como COM3.' }
    $nic = (Read-Host 'IPv4 privada de ESTA PC para conectar el C66 (Enter para usar solo la PC)').Trim()
    if ($nic -and $nic -notmatch '^(10|192\.168|172\.(1[6-9]|2[0-9]|3[01]))\.' ) { throw 'El C66 requiere una IPv4 de la red privada.' }
    if ($nic) {
        $addresses = foreach ($adapter in [Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
            foreach ($entry in $adapter.GetIPProperties().UnicastAddresses) { $entry.Address.ToString() }
        }
        if ($nic -notin $addresses) { throw 'La direccion indicada no corresponde a una interfaz IPv4 local.' }
    }
    $temporary = Join-Path $Directorio ([guid]::NewGuid().ToString() + '.tmp')
    @{ puerto = $port; redC66 = $nic } | ConvertTo-Json | Set-Content -Encoding ASCII -LiteralPath $temporary
    if (Test-Path -LiteralPath $configPath) {
        [IO.File]::Replace($temporary, $configPath, "$configPath.bak")
    } else { [IO.File]::Move($temporary, $configPath) }
}

if ($Accion -eq 'Instalar') {
    $manifestPath = Join-Path $PSScriptRoot 'paquete.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $files = @($exeName, 'Mesa.ps1', 'LEEME.txt')
    $tag = (Get-MesaSha $manifestPath).Substring(0,16)
    $target = Join-Path $Directorio "versiones\$tag"
    foreach ($file in $files) {
        if ((Get-MesaSha (Join-Path $PSScriptRoot $file)) -ne $manifest.$file) {
            throw "Archivo incompleto: $file. Extraiga de nuevo el ZIP."
        }
    }
    if (-not (Test-Path -LiteralPath $target)) {
        $versions = New-Item -ItemType Directory -Force -Path (Join-Path $Directorio 'versiones')
        $staging = New-Item -ItemType Directory -Path (Join-Path $versions.FullName ([guid]::NewGuid().ToString()))
        foreach ($file in $files) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $staging.FullName }
        Move-Item -LiteralPath $staging.FullName -Destination $target
    }
    foreach ($file in $files) {
        if ((Get-MesaSha (Join-Path $target $file)) -ne $manifest.$file) {
            throw "Copia instalada incompleta: $file."
        }
    }
    $ws = New-Object -ComObject WScript.Shell
    foreach ($item in @(@('Mesa de pesaje (piloto)','Iniciar'), @('Estación 2 - Inventario y retornos','Iniciar -Central'), @('Configurar balanza de mesa','Configurar'))) {
        $shortcut = $ws.CreateShortcut((Join-Path $Escritorio ($item[0] + '.lnk')))
        $shortcut.TargetPath = (Get-Command powershell.exe).Source
        $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $target 'Mesa.ps1') + '" -Directorio "' + $Directorio + '" -Accion ' + $item[1]
        $shortcut.WorkingDirectory = $target
        $shortcut.Save()
    }
    Write-Host 'Instalada. Abra Mesa de pesaje (piloto) desde el escritorio.'
    if (-not $SinPausa) { Read-Host 'Pulse Enter para terminar' | Out-Null }
    return
}

if ($Accion -eq 'Configurar') { Set-Conexion; Write-Host 'Conexion guardada. Vuelva a iniciar la mesa.'; return }
$config = $null
$runArgs = @('--db', $dbPath, '--open-browser')
if ($Central) {
    $settings = Get-Content -LiteralPath (Join-Path $Directorio 'central.json') -Raw | ConvertFrom-Json
    if (-not $settings.url -or -not $settings.credencial) { throw 'Falta configurar la cuenta de Estacion 2.' }
    $credential = ConvertTo-SecureString $settings.credencial
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential)
    try { $env:MESA_CENTRAL_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    $runArgs = @('--db', (Join-Path $Directorio 'datos-central\dispositivo.sqlite3'), '--central', $settings.url, '--open-browser')
}
if (Test-Path -LiteralPath $configPath) {
    $config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
    if ($config.puerto -notmatch '^COM[1-9][0-9]{0,3}$') { throw 'Configure otra vez el puerto de la Accura.' }
    $runArgs += @('--scale-port', $config.puerto)
} else {
    $runArgs += '--scale-unconfigured'
}
if ($config.redC66) { $runArgs += @('--c66-host', $config.redC66) }
if ($Central) { Write-Host 'Estación 2 conectada al SCM. Mantenga abierta esta ventana.' }
else { Write-Host 'Mesa de pesaje (piloto local). Mantenga abierta esta ventana durante la prueba.' }
& (Join-Path $PSScriptRoot $exeName) @runArgs
if ($Central) { Remove-Item Env:MESA_CENTRAL_TOKEN -ErrorAction SilentlyContinue }
if ($LASTEXITCODE -ne 0) { Read-Host 'La mesa no pudo iniciarse. Revise el mensaje anterior y pulse Enter' | Out-Null; exit 1 }
