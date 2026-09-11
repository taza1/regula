param(
    [int]$Port = 8000,
    [ValidateSet('local', 'openalex', 'crossref', 'arxiv', 'scholarly_with_local_fallback', 'openalex_with_local_fallback')]
    [string]$SourceConnector = 'local',
    [string]$OpenAlexMailto = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSCommandPath

$env:MODEL_PROVIDER = 'mock'
$env:SOURCE_CONNECTOR = $SourceConnector
if ($OpenAlexMailto) {
    $env:OPENALEX_MAILTO = $OpenAlexMailto
}
$env:LOCAL_DB_PATH = Join-Path $projectRoot 'data\research_system.db'

Set-Location -LiteralPath $projectRoot
python -m uvicorn src.main:app --host 127.0.0.1 --port $Port
