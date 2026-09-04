param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$')]
    [string]$Version,
    [string]$OutputDirectory,
    [switch]$SkipWheelhouse
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$moduleRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $moduleRoot 'artifacts'
}
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
$stagingRoot = [IO.Path]::GetFullPath((Join-Path $outputRoot ".staging-$Version-$([guid]::NewGuid().ToString('N'))"))
if (-not $stagingRoot.StartsWith($outputRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'El directorio temporal del release quedo fuera del directorio de artefactos.'
}

function Invoke-Checked {
    param([scriptblock]$Command, [string]$FailureMessage)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (codigo $LASTEXITCODE)"
    }
}

function Get-CleanGitRevision {
    param([Parameter(Mandatory = $true)][string]$RepositoryRoot)

    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        throw 'Git es obligatorio para construir un release trazable.'
    }

    $insideWorkTree = @(& $git.Source -C $RepositoryRoot rev-parse --is-inside-work-tree 2>&1)
    if ($LASTEXITCODE -ne 0 -or @($insideWorkTree).Count -eq 0 -or $insideWorkTree[-1].ToString().Trim() -ne 'true') {
        throw 'El origen del release no es un árbol de trabajo Git válido.'
    }

    $dirtyEntries = @(& $git.Source -C $RepositoryRoot status --porcelain=v1 --untracked-files=all 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw 'No se pudo comprobar el estado del árbol Git antes de empaquetar.'
    }
    if (@($dirtyEntries).Count -gt 0) {
        throw 'El árbol Git contiene cambios versionados o archivos nuevos. Confirme el código y deje el árbol limpio antes de construir el release.'
    }

    $revisionOutput = @(& $git.Source -C $RepositoryRoot rev-parse --verify HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or @($revisionOutput).Count -eq 0) {
        throw 'No se pudo resolver HEAD para el manifiesto del release.'
    }
    $revision = ([string]$revisionOutput[-1]).Trim()
    if ($revision -notmatch '^[0-9a-fA-F]{40,64}$') {
        throw 'HEAD no devolvió una revisión Git válida.'
    }
    return $revision.ToLowerInvariant()
}

function Get-BuildPython {
    param([Parameter(Mandatory = $true)][string]$RepositoryRoot)

    $candidates = @(
        (Join-Path $RepositoryRoot 'backend\.venv\Scripts\python.exe'),
        (Join-Path $RepositoryRoot 'backend\venv\Scripts\python.exe')
    )
    $pathPython = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($pathPython) {
        $candidates += $pathPython.Source
    }

    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        $version = @(& $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1)
        if (
            $LASTEXITCODE -eq 0 -and
            @($version).Count -gt 0 -and
            $version[-1].ToString().Trim() -eq '3.12'
        ) {
            return $candidate
        }
    }

    throw 'No se encontro Python 3.12 para construir el release.'
}

function Assert-NewReleaseArtifact {
    param([Parameter(Mandatory = $true)][string]$ArchivePath)
    foreach ($candidate in @($ArchivePath, "$ArchivePath.sha256")) {
        if (Test-Path -LiteralPath $candidate) {
            throw "Ya existe el artefacto inmutable $candidate. Use una versión nueva; nunca sobrescriba un ZIP o sidecar publicado."
        }
    }
}

function Copy-ReleaseTree {
    param([string]$Source, [string]$Destination)
    $sourceRoot = [IO.Path]::GetFullPath($Source)
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
        $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart('\', '/')
        $relative -notmatch '(^|[\\/])(venv|\.venv|__pycache__|\.pytest_cache|tests|instance|logs|\.git)([\\/]|$)' -and
        $relative -notmatch '\.(py[co]|log)$'
    } | ForEach-Object {
        $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart('\', '/')
        $target = Join-Path $Destination $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $target
    }
}

$archiveName = "envaperu-pesaje-$Version-win-x64.zip"
$archivePath = Join-Path $outputRoot $archiveName
Assert-NewReleaseArtifact -ArchivePath $archivePath
$sourceRevision = Get-CleanGitRevision -RepositoryRoot $moduleRoot

try {
    New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null

    Push-Location (Join-Path $moduleRoot 'frontend')
    try {
        Invoke-Checked { npm ci } 'No se pudieron instalar las dependencias del frontend'
        Invoke-Checked { npm run build } 'No se pudo compilar el frontend'
    }
    finally {
        Pop-Location
    }

    Copy-ReleaseTree (Join-Path $moduleRoot 'backend\app') (Join-Path $stagingRoot 'backend\app')
    Copy-ReleaseTree (Join-Path $moduleRoot 'backend\contracts') (Join-Path $stagingRoot 'backend\contracts')
    @(
        'requirements-runtime.lock',
        'station_control.py',
        'station_history.py',
        'station_main.py',
        'station_release.py',
        'station_storage.py'
    ) | ForEach-Object {
        Copy-Item -LiteralPath (Join-Path $moduleRoot "backend\$_") -Destination (Join-Path $stagingRoot "backend\$_")
    }
    Copy-ReleaseTree (Join-Path $moduleRoot 'release') (Join-Path $stagingRoot 'release')
    Copy-ReleaseTree (Join-Path $moduleRoot 'frontend\dist') (Join-Path $stagingRoot 'frontend\dist')

    $runtimeLock = Join-Path $stagingRoot 'backend\requirements-runtime.lock'
    if (-not (Test-Path -LiteralPath $runtimeLock)) {
        throw 'El release no contiene requirements-runtime.lock.'
    }

    $repoPython = Get-BuildPython -RepositoryRoot $moduleRoot

    if (-not $SkipWheelhouse) {
        $wheelhouse = Join-Path $stagingRoot 'wheels'
        New-Item -ItemType Directory -Path $wheelhouse -Force | Out-Null
        Invoke-Checked {
            & $repoPython -m pip download --only-binary=:all: --dest $wheelhouse --requirement $runtimeLock
        } 'No se pudo construir el wheelhouse offline'
    }
    else {
        New-Item -ItemType Directory -Path (Join-Path $stagingRoot 'wheels') -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $stagingRoot 'wheels\SKIPPED_FOR_TESTS.txt') -Value 'Wheelhouse omitted by explicit test flag.'
    }

    $confirmedSourceRevision = Get-CleanGitRevision -RepositoryRoot $moduleRoot
    if (-not [string]::Equals($sourceRevision, $confirmedSourceRevision, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'HEAD cambió durante la construcción. Descarte el staging y vuelva a generar el release.'
    }
    Invoke-Checked {
        & $repoPython (Join-Path $moduleRoot 'backend\station_release.py') manifest `
            --root $stagingRoot `
            --version $Version `
            --source-revision $sourceRevision | Out-Null
    } 'No se pudo generar el manifiesto del release'

    Compress-Archive -Path (Join-Path $stagingRoot '*') -DestinationPath $archivePath -CompressionLevel Optimal
    $sha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$archivePath.sha256" -Value "$sha256  $archiveName" -Encoding ascii

    Write-Output "RELEASE_BUILT version=$Version"
    Write-Output "PACKAGE=$archivePath"
    Write-Output "SHA256=$sha256"
}
finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        $resolved = [IO.Path]::GetFullPath($stagingRoot)
        if ($resolved.StartsWith($outputRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
}
