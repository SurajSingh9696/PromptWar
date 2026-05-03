param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [string]$ServiceName = "votewise-india",
    [string]$Region = "asia-south1",
    [switch]$SkipTests,
    [string]$GeminiApiKey = $env:GEMINI_API_KEY,
    [string]$ActiveModel = "gemini-2.5-flash"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($GeminiApiKey)) {
    throw "Gemini API key missing. Pass -GeminiApiKey or set GEMINI_API_KEY env var."
}

Write-Host "Installing dependencies..."
python -m pip install --upgrade pip
pip install -r functions\requirements.txt -r requirements-test.txt

if (-not $SkipTests) {
    Write-Host "Running tests..."
    $env:PYTHONPATH = "."
    pytest tests\ -v
}

Write-Host "Setting gcloud project..."
gcloud config set project $ProjectId

Write-Host "Deploying to Cloud Run..."
gcloud run deploy $ServiceName `
    --project $ProjectId `
    --region $Region `
    --source . `
    --allow-unauthenticated `
    --set-env-vars "GEMINI_API_KEY=$GeminiApiKey,ACTIVE_MODEL=$ActiveModel"

Write-Host ""
Write-Host "Deployment finished."
