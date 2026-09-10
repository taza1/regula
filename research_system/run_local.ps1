param(
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSCommandPath

$env:MODEL_PROVIDER = 'mock'
$env:LOCAL_DB_PATH = Join-Path $projectRoot 'data\research_system.db'

Set-Location -LiteralPath $projectRoot
python -m uvicorn src.main:app --host 127.0.0.1 --port $Port
