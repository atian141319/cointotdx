param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $ProjectRoot
try {
    & $Python -m venv "$PSScriptRoot\.build-venv"
    if ($LASTEXITCODE -ne 0) { throw 'venv failed' }
    $BuildPython = "$PSScriptRoot\.build-venv\Scripts\python.exe"
    & $BuildPython -m pip install -r "$PSScriptRoot\requirements-build.txt"
    if ($LASTEXITCODE -ne 0) { throw 'dependency installation failed' }
    & $BuildPython -m PyInstaller --noconfirm --clean --windowed --onefile --name CryptoTdxSync --paths $ProjectRoot --paths $PSScriptRoot --distpath "$PSScriptRoot\release" --workpath "$PSScriptRoot\build" --specpath $PSScriptRoot "$PSScriptRoot\app.py"
    if ($LASTEXITCODE -ne 0) { throw 'build failed' }
} finally { Pop-Location }
