# Start the desktop demo. The API key is read from the environment or an untracked .env.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "virtual environment not found: run 'uv venv .venv' and 'uv pip install -e .' first" }
$env:PYTHONUTF8 = "1"
Set-Location $root
& $python -m app.main
