$ErrorActionPreference = "Stop"

$defaultPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (Test-Path $defaultPython) {
    $python = $defaultPython
} else {
    throw "Không tìm thấy môi trường Python. Hãy tạo .venv và cài requirements.txt trước."
}

Push-Location $PSScriptRoot
try {
    & $python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
