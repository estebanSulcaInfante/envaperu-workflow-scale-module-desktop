import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = REPOSITORY_ROOT / "release"
RELEASE_RUNBOOK = REPOSITORY_ROOT / "RUNBOOK_ACTUALIZACION_PC_PILOTO.md"
BUILD_SCRIPT = RELEASE_DIR / "Build-StationRelease.ps1"
UPDATE_SCRIPT = RELEASE_DIR / "Update-Station.ps1"
ROLLBACK_SCRIPT = RELEASE_DIR / "Rollback-Station.ps1"
MIGRATE_LEGACY_SCRIPT = RELEASE_DIR / "Migrate-LegacyStation.ps1"
INSPECT_SCRIPT = RELEASE_DIR / "Inspect-Station.ps1"
START_SCRIPT = RELEASE_DIR / "Start-ActiveStation.ps1"
WINDOWS_POWERSHELL = Path(
    os.environ.get("SystemRoot", r"C:\Windows")
) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def _require_windows_powershell_5() -> Path:
    if os.name != "nt" or not WINDOWS_POWERSHELL.is_file():
        pytest.skip("Windows PowerShell 5.1 is only available on Windows")

    version = subprocess.run(
        [
            str(WINDOWS_POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$PSVersionTable.PSVersion.Major",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if version != "5":
        pytest.skip(f"Expected Windows PowerShell 5, found major version {version}")
    return WINDOWS_POWERSHELL


def _run_windows_powershell(script_path: Path, *arguments: str, env=None):
    powershell = _require_windows_powershell_5()
    return subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            *arguments,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def test_release_scripts_parse_with_windows_powershell_5(tmp_path):
    harness = tmp_path / "parse-release-scripts.ps1"
    harness.write_text(
        """param([Parameter(Mandatory = $true)][string]$ReleaseDirectory)
$failed = $false
Get-ChildItem -LiteralPath $ReleaseDirectory -Filter '*.ps1' -File | ForEach-Object {
    $tokens = $null
    $parseErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $_.FullName,
        [ref]$tokens,
        [ref]$parseErrors
    )
    if ($parseErrors.Count -gt 0) {
        $failed = $true
        $parseErrors | ForEach-Object { Write-Error "$($_.Extent.File): $($_.Message)" }
    }
}
if ($failed) { exit 1 }
""",
        encoding="utf-8",
    )

    result = _run_windows_powershell(
        harness,
        "-ReleaseDirectory",
        str(RELEASE_DIR),
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_background_launcher_preserves_arguments_with_spaces(tmp_path):
    _require_windows_powershell_5()
    install_root = tmp_path / "Program Files" / "EnvaPeru" / "Pesaje"
    release_path = install_root / "releases" / "1.2.0-probe"
    backend_path = release_path / "backend"
    data_root = tmp_path / "Program Data" / "EnvaPeru" / "Pesaje"
    marker = tmp_path / "background-launch.json"
    python_path = backend_path / "venv" / "Scripts" / "python.exe"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "venv",
            "--without-pip",
            str(backend_path / "venv"),
        ],
        check=True,
    )
    (backend_path / "station_main.py").write_text(
        """import json
import os
import sys
from pathlib import Path

Path(os.environ["LAUNCH_PROBE"]).write_text(
    json.dumps(sys.argv[1:]), encoding="utf-8"
)
""",
        encoding="utf-8",
    )
    (data_root / "run").mkdir(parents=True)
    (data_root / "run" / "active-release.json").write_text(
        json.dumps(
            {
                "active_version": "1.2.0-probe",
                "active_path": str(release_path),
            }
        ),
        encoding="utf-8",
    )
    assert python_path.is_file()

    env = os.environ.copy()
    env["LAUNCH_PROBE"] = str(marker)
    result = _run_windows_powershell(
        START_SCRIPT,
        "-InstallRoot",
        str(install_root),
        "-DataRoot",
        str(data_root),
        "-StationId",
        "PESAJE PRUEBA 01",
        "-Port",
        "5059",
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    deadline = time.monotonic() + 5
    while not marker.is_file() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert marker.is_file(), result.stdout + result.stderr
    assert json.loads(marker.read_text(encoding="utf-8")) == [
        "--station-id",
        "PESAJE PRUEBA 01",
        "--port",
        "5059",
    ]


def test_bootstrap_python_detection_executes_with_windows_powershell_5(tmp_path):
    if sys.version_info[:2] != (3, 12):
        pytest.skip("This regression test needs the Python 3.12 test runtime")

    harness = tmp_path / "invoke-bootstrap-detection.ps1"
    harness.write_text(
        """param([Parameter(Mandatory = $true)][string]$UpdateScript)
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $UpdateScript,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) {
    $parseErrors | ForEach-Object { Write-Error $_.Message }
    exit 2
}
$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Find-BootstrapPython'
}, $true)
if (-not $functionAst) {
    Write-Error 'Find-BootstrapPython was not found.'
    exit 3
}
. ([ScriptBlock]::Create($functionAst.Extent.Text))
$resolved = Find-BootstrapPython
if (-not $resolved) { exit 4 }
Write-Output $resolved
""",
        encoding="utf-8",
    )

    python_directory = str(Path(sys.executable).resolve().parent)
    env = os.environ.copy()
    env["PATH"] = python_directory + os.pathsep + env.get("PATH", "")
    result = _run_windows_powershell(
        harness,
        "-UpdateScript",
        str(UPDATE_SCRIPT),
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    resolved = Path(result.stdout.strip().splitlines()[-1])
    assert resolved.name.lower() == "python.exe"
    assert shutil.which("python", path=python_directory) is not None
    assert resolved.resolve() == Path(sys.executable).resolve()


def test_legacy_bridge_reuses_python312_from_selected_installation(tmp_path):
    if sys.version_info[:2] != (3, 12):
        pytest.skip("This regression test needs the Python 3.12 test runtime")

    harness = tmp_path / "invoke-legacy-bootstrap-detection.ps1"
    harness.write_text(
        """param(
    [Parameter(Mandatory = $true)][string]$MigrationScript,
    [Parameter(Mandatory = $true)][string]$LegacyPython
)
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $MigrationScript,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) { exit 2 }
foreach ($name in @('Test-Python312', 'Find-BootstrapPython')) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if (-not $functionAst) { exit 3 }
    . ([ScriptBlock]::Create($functionAst.Extent.Text))
}
$resolved = Find-BootstrapPython -TrustedLegacyCandidates @($LegacyPython)
if (-not $resolved) { exit 4 }
Write-Output $resolved
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    windows_root = Path(env.get("SystemRoot", r"C:\Windows"))
    env["PATH"] = os.pathsep.join(
        [str(WINDOWS_POWERSHELL.parent), str(windows_root / "System32")]
    )
    result = _run_windows_powershell(
        harness,
        "-MigrationScript",
        str(MIGRATE_LEGACY_SCRIPT),
        "-LegacyPython",
        str(Path(sys.executable).resolve()),
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(result.stdout.strip().splitlines()[-1]).resolve() == Path(
        sys.executable
    ).resolve()
    source = MIGRATE_LEGACY_SCRIPT.read_text(encoding="utf-8")
    assert "Join-Path $legacyBackend '.venv\\Scripts\\python.exe'" in source
    assert "Join-Path $legacyBackend 'venv\\Scripts\\python.exe'" in source


def test_hybrid_adoption_archives_and_restores_database_family_on_powershell_5(
    tmp_path,
):
    database = tmp_path / "data" / "pesajes.db"
    database.parent.mkdir(parents=True)
    database.write_text("authoritative-db", encoding="utf-8")
    Path(f"{database}-wal").write_text("authoritative-wal", encoding="utf-8")
    Path(f"{database}-shm").write_text("authoritative-shm", encoding="utf-8")
    archive = tmp_path / "backups" / "partial-adoption"
    harness = tmp_path / "invoke-partial-adoption-recovery.ps1"
    harness.write_text(
        """param(
    [Parameter(Mandatory = $true)][string]$MigrationScript,
    [Parameter(Mandatory = $true)][string]$DatabasePath,
    [Parameter(Mandatory = $true)][string]$ArchivePath
)
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $MigrationScript,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) { exit 2 }
foreach ($name in @('Move-DatabaseFamilyToArchive', 'Restore-DatabaseFamilyFromArchive')) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if (-not $functionAst) { exit 3 }
    . ([ScriptBlock]::Create($functionAst.Extent.Text))
}
$moved = @(Move-DatabaseFamilyToArchive $DatabasePath $ArchivePath)
if ($moved.Count -ne 3 -or (Test-Path -LiteralPath $DatabasePath)) { exit 4 }
Set-Content -LiteralPath $DatabasePath -Value 'failed-import' -Encoding UTF8
Restore-DatabaseFamilyFromArchive $DatabasePath $ArchivePath
if ((Get-Content -LiteralPath $DatabasePath -Raw).Trim() -ne 'authoritative-db') { exit 5 }
if ((Get-Content -LiteralPath "$DatabasePath-wal" -Raw).Trim() -ne 'authoritative-wal') { exit 6 }
if ((Get-Content -LiteralPath "$DatabasePath-shm" -Raw).Trim() -ne 'authoritative-shm') { exit 7 }
$failed = @(Get-ChildItem -LiteralPath $ArchivePath -Directory -Filter 'failed-import-*')
if ($failed.Count -ne 1) { exit 8 }
Write-Output 'RECOVERY_OK'
""",
        encoding="utf-8",
    )

    result = _run_windows_powershell(
        harness,
        "-MigrationScript",
        str(MIGRATE_LEGACY_SCRIPT),
        "-DatabasePath",
        str(database),
        "-ArchivePath",
        str(archive),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-1] == "RECOVERY_OK"


def test_bootstrap_python_falls_back_to_trusted_active_runtime_on_powershell_5(
    tmp_path,
):
    if sys.version_info[:2] != (3, 12):
        pytest.skip("This regression test needs the Python 3.12 test runtime")

    harness = tmp_path / "invoke-active-python-fallback.ps1"
    harness.write_text(
        """param(
    [Parameter(Mandatory = $true)][string]$UpdateScript,
    [Parameter(Mandatory = $true)][string]$TrustedPython
)
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $UpdateScript,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) { exit 2 }
$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Find-BootstrapPython'
}, $true)
if (-not $functionAst) { exit 3 }
. ([ScriptBlock]::Create($functionAst.Extent.Text))
$resolved = Find-BootstrapPython -TrustedActivePython $TrustedPython
if (-not $resolved) { exit 4 }
Write-Output $resolved
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
    result = _run_windows_powershell(
        harness,
        "-UpdateScript",
        str(UPDATE_SCRIPT),
        "-TrustedPython",
        str(Path(sys.executable).resolve()),
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(result.stdout.strip().splitlines()[-1]).resolve() == Path(
        sys.executable
    ).resolve()


def test_release_builder_rejects_dirty_git_tree_with_windows_powershell_5(tmp_path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git is required for the release source revision gate")

    repository = tmp_path / "source-repository"
    repository.mkdir()
    subprocess.run([git, "init"], cwd=repository, check=True, capture_output=True)
    subprocess.run(
        [git, "config", "user.email", "release-test@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        [git, "config", "user.name", "Release Test"],
        cwd=repository,
        check=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("committed\n", encoding="utf-8")
    subprocess.run([git, "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(
        [git, "commit", "-m", "initial"],
        cwd=repository,
        check=True,
        capture_output=True,
    )

    harness = tmp_path / "invoke-clean-git-revision.ps1"
    harness.write_text(
        """param(
    [Parameter(Mandatory = $true)][string]$BuildScript,
    [Parameter(Mandatory = $true)][string]$RepositoryRoot
)
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $BuildScript,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) { exit 2 }
$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-CleanGitRevision'
}, $true)
if (-not $functionAst) { exit 3 }
. ([ScriptBlock]::Create($functionAst.Extent.Text))
try {
    $revision = Get-CleanGitRevision -RepositoryRoot $RepositoryRoot
    Write-Output "CLEAN=$revision"
}
catch {
    Write-Error $_.Exception.Message
    exit 9
}
""",
        encoding="utf-8",
    )

    clean = _run_windows_powershell(
        harness,
        "-BuildScript",
        str(BUILD_SCRIPT),
        "-RepositoryRoot",
        str(repository),
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "CLEAN=" in clean.stdout

    tracked.write_text("modified\n", encoding="utf-8")
    dirty = _run_windows_powershell(
        harness,
        "-BuildScript",
        str(BUILD_SCRIPT),
        "-RepositoryRoot",
        str(repository),
    )
    assert dirty.returncode == 9
    assert "cambios versionados o archivos nuevos" in dirty.stderr

    tracked.write_text("committed\n", encoding="utf-8")
    (repository / "untracked.txt").write_text("new\n", encoding="utf-8")
    untracked = _run_windows_powershell(
        harness,
        "-BuildScript",
        str(BUILD_SCRIPT),
        "-RepositoryRoot",
        str(repository),
    )
    assert untracked.returncode == 9
    assert "cambios versionados o archivos nuevos" in untracked.stderr


def test_release_builder_rechecks_revision_before_writing_manifest():
    source = BUILD_SCRIPT.read_text(encoding="utf-8")

    initial = source.index(
        "$sourceRevision = Get-CleanGitRevision -RepositoryRoot $moduleRoot"
    )
    confirmed = source.index(
        "$confirmedSourceRevision = Get-CleanGitRevision", initial
    )
    manifest = source.index("station_release.py') manifest", confirmed)

    assert "--porcelain=v1 --untracked-files=all" in source
    assert "sourceRevision = 'unknown'" not in source
    assert initial < confirmed < manifest


def test_release_builder_rejects_an_existing_immutable_archive_or_sidecar(tmp_path):
    harness = tmp_path / "invoke-artifact-gate.ps1"
    harness.write_text(
        """param(
    [Parameter(Mandatory = $true)][string]$BuildScript,
    [Parameter(Mandatory = $true)][string]$ArchivePath
)
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $BuildScript,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) { exit 2 }
$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Assert-NewReleaseArtifact'
}, $true)
if (-not $functionAst) { exit 3 }
. ([ScriptBlock]::Create($functionAst.Extent.Text))
try {
    Assert-NewReleaseArtifact -ArchivePath $ArchivePath
    Write-Output 'ARTIFACT_PATH_AVAILABLE'
}
catch {
    Write-Error $_.Exception.Message
    exit 9
}
""",
        encoding="utf-8",
    )
    archive = tmp_path / "envaperu-pesaje-1.2.0-pilot.3-win-x64.zip"

    available = _run_windows_powershell(
        harness,
        "-BuildScript",
        str(BUILD_SCRIPT),
        "-ArchivePath",
        str(archive),
    )
    assert available.returncode == 0, available.stdout + available.stderr

    archive.with_suffix(archive.suffix + ".sha256").write_text(
        "reserved\n", encoding="ascii"
    )
    reserved = _run_windows_powershell(
        harness,
        "-BuildScript",
        str(BUILD_SCRIPT),
        "-ArchivePath",
        str(archive),
    )
    assert reserved.returncode == 9
    assert "artefacto inmutable" in reserved.stderr

    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "Remove-Item -LiteralPath $archivePath" not in source


def test_legacy_allowlist_removes_matching_single_and_double_quotes_in_ps5(tmp_path):
    legacy_environment = tmp_path / "legacy.env"
    legacy_environment.write_text(
        'SCALE_PORT="COM7"\n'
        "PRINTER_NAME='TSC TE200 Planta'\n"
        "TIMEZONE=America/Lima\n"
        'PRINTER_PORT="COM8\'\n',
        encoding="utf-8",
    )
    harness = tmp_path / "invoke-legacy-allowlist.ps1"
    harness.write_text(
        """param(
    [Parameter(Mandatory = $true)][string]$MigrationScript,
    [Parameter(Mandatory = $true)][string]$EnvironmentPath
)
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $MigrationScript,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) { exit 2 }
foreach ($name in @(
    'Read-EnvironmentFile',
    'ConvertFrom-LegacyEnvironmentValue',
    'Select-LegacyValue'
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if (-not $functionAst) { exit 3 }
    . ([ScriptBlock]::Create($functionAst.Extent.Text))
}
$values = Read-EnvironmentFile $EnvironmentPath
[ordered]@{
    scale_port = Select-LegacyValue $values 'SCALE_PORT' 'COM4'
    printer_name = Select-LegacyValue $values 'PRINTER_NAME' 'TSC TE200'
    timezone = Select-LegacyValue $values 'TIMEZONE' 'America/Lima'
    unmatched = Select-LegacyValue $values 'PRINTER_PORT' 'COM3'
} | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )

    result = _run_windows_powershell(
        harness,
        "-MigrationScript",
        str(MIGRATE_LEGACY_SCRIPT),
        "-EnvironmentPath",
        str(legacy_environment),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    values = json.loads(result.stdout)
    assert values == {
        "scale_port": "COM7",
        "printer_name": "TSC TE200 Planta",
        "timezone": "America/Lima",
        "unmatched": '"COM8\'',
    }


def test_runbook_only_unblocks_scripts_after_sha256_verification():
    source = RELEASE_RUNBOOK.read_text(encoding="utf-8")

    hash_command = source.index("certutil -hashfile $Zip SHA256")
    confirmed = source.index("Solo después de confirmar esa coincidencia", hash_command)
    unblock_zip = source.index("Unblock-File -LiteralPath $Zip", confirmed)
    extract = source.index("Expand-Archive", unblock_zip)
    unblock_scripts = source.index("-File | Unblock-File", extract)

    assert "powershell.exe -NoProfile -ExecutionPolicy Bypass -File" in source
    assert hash_command < confirmed < unblock_zip < extract < unblock_scripts


def test_update_repairs_and_verifies_an_existing_partial_runtime():
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    assert (
        "if (-not $SkipRuntimeInstall -and -not "
        "(Test-Path -LiteralPath $newPython))"
    ) not in source
    runtime_block = source.index("if (-not $SkipRuntimeInstall) {")
    create_venv = source.index("-m venv", runtime_block)
    install_offline = source.index("-m pip install --no-index", create_venv)
    verify_dependencies = source.index("-m pip check", install_offline)
    backup_block = source.index(
        "$backupPath = if ($resumingFirstActivation)", verify_dependencies
    )

    assert runtime_block < create_venv < install_offline < verify_dependencies < backup_block


def test_rollback_waits_for_health_and_port_shutdown_before_database_restore():
    source = ROLLBACK_SCRIPT.read_text(encoding="utf-8")

    wait_call = source.index("Wait-StationStopped -TimeoutSeconds 20")
    first_evidence = source.index("Assert-RollbackEvidence", wait_call)
    switch_pointer = source.index("$manager, 'rollback'", first_evidence)
    second_evidence = source.index("Assert-RollbackEvidence", switch_pointer)
    restore_database = source.index("'restore', ([string]$state.preupdate_backup)")
    ready = source.index("Wait-StationReady -ExpectedVersion", restore_database)
    complete = source.index('Write-Output "ROLLBACK_COMPLETE', ready)

    assert "Start-Sleep -Seconds 2" not in source
    assert "/api/local/v1/health/ready" in source
    assert "System.Net.Sockets.TcpClient" in source
    assert "$responseVersion -eq $ExpectedVersion" in source
    assert "-AllowMissingVersion" in source[ready:complete]
    assert (
        wait_call
        < first_evidence
        < switch_pointer
        < second_evidence
        < restore_database
        < ready
        < complete
    )


def test_update_requires_online_central_from_the_current_boot():
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    config = source.index("validate-pilot-config")
    activate = source.index("$managerScript, 'activate'", config)
    ready = source.index("Wait-StationState -Ready $true")
    central = source.index("Wait-CentralOnline -ExpectedVersion $version -TimeoutSeconds 90", ready)
    complete = source.index('Write-Output "UPDATE_COMPLETE', central)

    assert "response.central.state -eq 'ONLINE'" in source
    assert "$responseVersion -eq $ExpectedVersion" in source
    assert config < activate < ready < central < complete


def test_update_rejects_runtime_skip_in_productive_mode_and_same_version():
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    skip_gate = source.index("$SkipRuntimeInstall -and -not $NoStart")
    stage = source.index("$managerScript, 'stage'", skip_gate)
    same_version = source.index("active_version) -eq $version", stage)
    runtime = source.index("if (-not $SkipRuntimeInstall) {", same_version)
    backup = source.index(
        "if (-not $resumingFirstActivation -and "
        "(Test-Path -LiteralPath $databasePath)) {",
        runtime,
    )

    assert "SkipRuntimeInstall solo se admite junto con -NoStart" in source
    assert "-not $SkipRuntimeInstall" not in source[backup : backup + 100]
    assert skip_gate < stage < same_version < runtime < backup


def test_update_has_an_explicit_safe_resume_for_failed_first_activation():
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    resume_gate = source.index("if ($ResumeFirstActivation)")
    baseline_gate = source.index("$hasBaseline", resume_gate)
    same_version_reject = source.index("elseif ($previousState", baseline_gate)
    reused_backup = source.index(
        "$backupPath = if ($resumingFirstActivation)", same_version_reject
    )
    resume_branch = source.index(
        "if ($resumingFirstActivation) {", reused_backup
    )
    resume_event = source.index("FIRST_ACTIVATION_RESUMED", resume_branch)
    activate = source.index("$managerScript, 'activate'", resume_event)
    catch_block = source.index("catch {", source.index("UPDATE_COMPLETE"))
    retry_guard = source.index("if ($resumingFirstActivation)", catch_block)
    previous_branch = source.index("if (-not $previousState)", retry_guard)

    assert "-ResumeFirstActivation exige completar el arranque" in source
    assert "corrija la causa y repita con -ResumeFirstActivation" in source
    assert (
        resume_gate
        < baseline_gate
        < same_version_reject
        < reused_backup
        < resume_branch
        < resume_event
        < activate
        < catch_block
        < retry_guard
        < previous_branch
    )


def test_update_uses_only_a_confined_active_python_312_fallback():
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    assert "Get-TrustedActivePython" in source
    assert "Join-Path $resolvedPath 'backend\\venv\\Scripts\\python.exe'" in source
    assert "sys.version_info[:2] != (3, 12)" in source
    assert "StartsWith($releasesRoot + [IO.Path]::DirectorySeparatorChar" in source


def test_update_checks_operational_evidence_on_both_sides_of_pointer_rollback():
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    catch_block = source.index("catch {", source.index('Write-Output "UPDATE_COMPLETE'))
    first_evidence = source.index("Assert-RollbackEvidence", catch_block)
    rollback = source.index("$managerScript, 'rollback'", first_evidence)
    second_evidence = source.index("Assert-RollbackEvidence", rollback)
    restore = source.index("'restore', $backupPath", second_evidence)

    assert "compare-operational" in source
    assert "OPERATIONAL_STATE_MATCH" in source
    assert first_evidence < rollback < second_evidence < restore


def test_update_restores_preupdate_backup_when_offline_migration_fails():
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    catch_block = source.index("catch {", source.index('Write-Output "UPDATE_COMPLETE'))
    inactive_branch = source.index(
        "elseif ($backupPath -and $authoritativeMigrationStarted)",
        catch_block,
    )
    restore = source.index("'restore', $backupPath", inactive_branch)
    restart_previous = source.index("Start-ActiveStation.ps1", restore)

    assert inactive_branch < restore < restart_previous


def test_update_waits_for_port_release_before_automatic_restore():
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    stop_wait = source.index("Wait-StationState -Ready $false")
    rollback = source.index("$managerScript, 'rollback'", stop_wait)
    restore = source.index("'restore', $backupPath", rollback)

    assert "System.Net.Sockets.TcpClient" in source
    assert "-not $Ready -and -not (Test-LoopbackPortOpen)" in source
    assert stop_wait < rollback < restore


def test_port_fallback_does_not_treat_time_wait_as_a_listener():
    for script in (UPDATE_SCRIPT, ROLLBACK_SCRIPT):
        source = script.read_text(encoding="utf-8")

        assert r"\s+LISTENING\s+\d+" in source
        assert r"\s+\S+\s+\d+\s*$" not in source


def test_update_omits_empty_preupdate_backup_argument_on_first_install():
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    arguments = source.index("$activateArguments = @(")
    conditional = source.index("if ($backupPath) {", arguments)
    invocation = source.index("Invoke-CheckedPython $bootstrapPython $activateArguments", conditional)

    assert arguments < conditional < invocation
    assert "'--preupdate-backup', ([string]$backupPath)" in source[conditional:invocation]


def test_update_requires_an_authoritative_database_or_explicit_clean_install():
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    database_gate = source.index("$databaseExists = Test-Path")
    partial_gate = source.index("-not $PreparedLegacyMigration", database_gate)
    empty_gate = source.index("-not $AllowEmptyStation", partial_gate)
    stage = source.index("$managerScript, 'stage'", empty_gate)

    assert database_gate < partial_gate < empty_gate < stage


def test_update_stops_station_before_authoritative_backup_and_activation():
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    stop = source.index("if ($previousPath) { Stop-Release $previousPath }")
    port_gate = source.index("if (Test-LoopbackPortOpen)", stop)
    backup = source.index("'backup', '--reason'", port_gate)
    migrate_copy = source.index("'migrate'", backup)
    activate = source.index("$managerScript, 'activate'", migrate_copy)

    stop_function = source[source.index("function Stop-Release"):stop]
    assert "no tiene runtime/control verificable" in stop_function
    assert stop < port_gate < backup < migrate_copy < activate


def test_update_registers_operational_user_task_before_completion():
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    central = source.index("CENTRAL_ONLINE")
    task = source.index("Install-StationTask.ps1", central)
    task_ready = source.index("STATION_TASK_READY", task)
    complete = source.index("UPDATE_COMPLETE", task_ready)

    assert "Resolve-AccountSid" in source
    assert central < task < task_ready < complete


def test_legacy_bridge_stages_imports_and_only_then_activates_once():
    source = MIGRATE_LEGACY_SCRIPT.read_text(encoding="utf-8")

    reject_versioned = source.index("active-release.json")
    stage = source.index("$managerScript, 'stage'", reject_versioned)
    runtime = source.index("-m pip install --no-index", stage)
    provision = source.index("provision-token --data-root", runtime)
    imported = source.index("'import-legacy', $importDatabasePath", provision)
    identity = source.index("initialize-identity", imported)
    activated = source.index("$updateScript", identity)
    complete = source.index("LEGACY_MIGRATION_COMPLETE", activated)

    assert "-NoStart" not in source
    assert "-PreparedLegacyMigration" in source[activated:complete]
    assert (
        reject_versioned
        < stage
        < runtime
        < provision
        < imported
        < identity
        < activated
        < complete
    )


def test_hybrid_bridge_requires_explicit_adoption_and_preserves_recovery_evidence():
    source = MIGRATE_LEGACY_SCRIPT.read_text(encoding="utf-8")

    same_database = source.index("$sameProgramDataDatabase")
    explicit_gate = source.index("-not $AdoptExistingProgramDataDatabase", same_database)
    backup = source.index("pre-partial-adoption-$version", explicit_gate)
    archive = source.index("Move-DatabaseFamilyToArchive", backup)
    imported = source.index("'import-legacy', $importDatabasePath", archive)
    restore = source.index("Restore-DatabaseFamilyFromArchive", imported)
    evidence = source.index("partial_programdata_adoption", restore)

    assert "[switch]$ReuseExistingToken" in source
    assert "TOKEN_REUSED" in source
    assert "PARTIAL_DATABASE_RESTORED" in source
    assert explicit_gate < backup < archive < imported < restore < evidence


def test_update_accepts_an_explicit_python312_without_changing_global_path():
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    parameter = source.index("[string]$BootstrapPythonPath")
    validation = source.index("El runtime indicado no es Python 3.12")
    resolution = source.index("-ExplicitPython $BootstrapPythonPath", validation)

    assert "SetEnvironmentVariable" not in source[parameter:resolution]
    assert parameter < validation < resolution


def test_inspection_classifies_ambiguous_installations_fail_closed():
    source = INSPECT_SCRIPT.read_text(encoding="utf-8")

    assert "'CONFLICT'" in source
    assert "'PARTIAL_VERSIONED'" in source
    assert "MULTIPLE_DATABASES_REQUIRE_EXPLICIT_SELECTION" in source
    assert "ready_for_versioned_update" in source
    assert "ready_for_legacy_bridge" in source


def test_inspection_executes_in_powershell_5_and_separates_legacy_bridge(tmp_path):
    legacy_root = tmp_path / "legacy"
    legacy_database = legacy_root / "backend" / "instance" / "pesajes.db"
    legacy_database.parent.mkdir(parents=True)
    legacy_database.write_bytes(b"legacy-evidence")
    (legacy_root / ".env").write_text(
        "SCALE_PORT=COM7\n"
        "PRINTER_NAME=TSC TE200 Planta\n"
        "SECRET_KEY=must-not-be-reported\n",
        encoding="utf-8",
    )
    install_root = tmp_path / "install"
    data_root = tmp_path / "data-root"

    result = _run_windows_powershell(
        INSPECT_SCRIPT,
        "-InstallRoot", str(install_root),
        "-DataRoot", str(data_root),
        "-LegacyRoot", str(legacy_root),
        "-LegacyDatabasePath", str(legacy_database),
        "-Port", "59998",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["installation_kind"] == "LEGACY"
    assert report["ready_for_legacy_bridge"] is True
    assert report["ready_for_versioned_update"] is False
    assert report["ready_for_update"] is False
    assert report["configuration"]["safe_values"]["SCALE_PORT"] == "COM7"
    assert "SECRET_KEY" not in report["configuration"]["safe_values"]

    versioned_database = data_root / "data" / "pesajes.db"
    versioned_database.parent.mkdir(parents=True)
    versioned_database.write_bytes(b"partial-versioned-evidence")
    conflict = _run_windows_powershell(
        INSPECT_SCRIPT,
        "-InstallRoot", str(install_root),
        "-DataRoot", str(data_root),
        "-LegacyRoot", str(legacy_root),
        "-LegacyDatabasePath", str(legacy_database),
        "-Port", "59998",
    )

    assert conflict.returncode == 0, conflict.stdout + conflict.stderr
    conflict_report = json.loads(conflict.stdout)
    assert conflict_report["installation_kind"] == "CONFLICT"
    assert conflict_report["ready_for_update"] is False
    assert "MULTIPLE_DATABASES_REQUIRE_EXPLICIT_SELECTION" in conflict_report["findings"]
