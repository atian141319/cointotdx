param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $ProjectRoot
try {
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'rate_control.py'))) { throw 'Missing local dependency: rate_control.py' }
    & $Python -m venv "$PSScriptRoot\.build-venv"
    if ($LASTEXITCODE -ne 0) { throw 'venv failed' }
    $BuildPython = "$PSScriptRoot\.build-venv\Scripts\python.exe"
    & $BuildPython -m pip install -r "$PSScriptRoot\requirements-build.txt"
    if ($LASTEXITCODE -ne 0) { throw 'dependency installation failed' }
    & $BuildPython -m PyInstaller --noconfirm --clean --windowed --onefile --name CryptoTdxSync --paths $ProjectRoot --paths $PSScriptRoot --hidden-import rate_control --distpath "$PSScriptRoot\release" --workpath "$PSScriptRoot\build" --specpath $PSScriptRoot "$PSScriptRoot\app.py"
    if ($LASTEXITCODE -ne 0) { throw 'build failed' }
} finally { Pop-Location }
