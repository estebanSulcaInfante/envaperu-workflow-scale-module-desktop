import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = REPOSITORY_ROOT / "release"
UPDATE_SCRIPT = RELEASE_DIR / "Update-Station.ps1"
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
