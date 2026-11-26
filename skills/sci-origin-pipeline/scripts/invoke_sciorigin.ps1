# Portable Auto-Discovery Launcher for SciOrigin Pipeline (100% ASCII for PowerShell 5.1/7 locale safety)
# Automatically locates a Python environment containing `originpro` (or falls back with --skip-origin)
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PipelineArgs
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunnerPy  = Join-Path $ScriptDir "run_pipeline.py"

$Candidates = @()
if ($env:SCIORIGIN_PYTHON) {
    $Candidates += $env:SCIORIGIN_PYTHON
}
if ($env:CONDA_PREFIX) {
    $Candidates += (Join-Path $env:CONDA_PREFIX "python.exe")
}

$UserHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
$EnvRoots = @(
    (Join-Path $UserHome ".conda\envs"),
    (Join-Path $UserHome "miniconda3\envs"),
    (Join-Path $UserHome "miniforge3\envs"),
    (Join-Path $UserHome "anaconda3\envs")
)
if ($env:SCIORIGIN_SKIP_PROGRAMDATA -ne "1") {
    $EnvRoots += @(
        "C:\ProgramData\Miniconda3\envs",
        "C:\ProgramData\Anaconda3\envs"
    )
}

foreach ($root in $EnvRoots) {
    if (Test-Path $root) {
        Get-ChildItem $root -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $p = Join-Path $_.FullName "python.exe"
            if ((Test-Path $p) -and ($Candidates -notcontains $p)) {
                $Candidates += $p
            }
        }
    }
}

$SysPy = (Get-Command python -ErrorAction SilentlyContinue)
if ($SysPy -and ($Candidates -notcontains $SysPy.Source)) {
    $Candidates += $SysPy.Source
}

$SelectedPy = $null
foreach ($py in $Candidates) {
    if ($py -and (Test-Path $py)) {
        $hasOp = & $py -c "import importlib.util; print(int(bool(importlib.util.find_spec('originpro'))))" 2>$null
        if ($hasOp -eq "1") {
            $SelectedPy = $py
            break
        }
    }
}

if (-not $SelectedPy) {
    foreach ($py in $Candidates) {
        if ($py -and (Test-Path $py)) {
            $SelectedPy = $py
            break
        }
    }
    if ($SelectedPy -and ($PipelineArgs -contains "run") -and ($PipelineArgs -notcontains "--skip-origin")) {
        Write-Warning "No Python env with 'originpro' detected; appending --skip-origin for offline fallback."
        $PipelineArgs += "--skip-origin"
    }
}

if (-not $SelectedPy) {
    throw "No usable Python 3.10+ environment found. Install Python + dependencies (pip install originpro numpy scipy pandas openpyxl pillow) or set SCIORIGIN_PYTHON to your python.exe path."
}

& $SelectedPy $RunnerPy @PipelineArgs
exit $LASTEXITCODE
