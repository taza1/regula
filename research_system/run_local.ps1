param(
    [int]$Port = 8000,
    [ValidateSet('local', 'openalex', 'crossref', 'arxiv', 'scholarly', 'scholarly_with_local_fallback', 'openalex_with_local_fallback')]
    [string]$SourceConnector = 'local',
    [string]$OpenAlexMailto = '',
    [string]$OpenAlexApiKey = '',
    [string]$CrossrefMailto = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSCommandPath

$env:MODEL_PROVIDER = 'mock'
$env:SOURCE_CONNECTOR = $SourceConnector
if ($OpenAlexMailto) {
    $env:OPENALEX_MAILTO = $OpenAlexMailto
}
if ($OpenAlexApiKey) {
    $env:OPENALEX_API_KEY = $OpenAlexApiKey
}
if ($CrossrefMailto) {
    $env:CROSSREF_MAILTO = $CrossrefMailto
}
$env:LOCAL_DB_PATH = Join-Path $projectRoot 'data\research_system.db'

Set-Location -LiteralPath $projectRoot
python -m uvicorn src.main:app --host 127.0.0.1 --port $Port
