param(
    [string]$Endpoint = $env:AZURE_OPENAI_ENDPOINT,
    [string]$Deployment = 'gpt-5.6-sol',
    [int]$Port = 8000,
    [ValidateSet('local', 'openalex', 'crossref', 'arxiv', 'scholarly', 'scholarly_with_local_fallback', 'openalex_with_local_fallback')]
    [string]$SourceConnector = 'scholarly',
    [string]$OpenAlexMailto = '',
    [string]$OpenAlexApiKey = '',
    [string]$CrossrefMailto = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSCommandPath

# DefaultAzureCredential uses the signed-in Azure CLI locally and managed
# identity after deployment. No Azure key is stored by this launcher.
az account show --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Azure CLI is not signed in. Run 'az login' and retry."
}
if (-not $Endpoint) {
    throw "Provide -Endpoint or set AZURE_OPENAI_ENDPOINT."
}
$env:MODEL_PROVIDER = 'azure'
$env:AZURE_OPENAI_ENDPOINT = $Endpoint
$env:OPENAI_DEPLOYMENT_ID = $Deployment
$env:AZURE_OPENAI_TOKEN_SCOPE = 'https://cognitiveservices.azure.com/.default'
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
