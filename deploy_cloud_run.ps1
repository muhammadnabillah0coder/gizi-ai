<#
.SYNOPSIS
  Deploy 1-perintah Nutrisi Cerdas ke Google Cloud Run (Region Jakarta asia-southeast2).
  Bebas layar tidur Streamlit Community Cloud, siap domain sendiri HTTPS & PWA.

.EXAMPLE
  $env:GEMINI_API_KEY="AIza..."
  $env:DATABASE_URL="postgresql://..."
  .\deploy_cloud_run.ps1 -ProjectId "proyek-gcp-anda" -ServiceName "nutrisi-cerdas"
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [string]$ServiceName = "nutrisi-cerdas",
    [string]$Region = "asia-southeast2",
    [int]$MinInstances = 0,
    [int]$MaxInstances = 5,
    [string]$Memory = "1Gi",
    [string]$Cpu = "1"
)

$ErrorActionPreference = "Stop"

if (-not $env:GEMINI_API_KEY) {
    Write-Error "Environment variable GEMINI_API_KEY wajib disetel sebelum menjalankan deploy."
    exit 1
}

Write-Host "[1/4] Memverifikasi kebersihan seed tkpi_nutrition.db..."
python sanitize_seed_db.py --check
if ($LASTEXITCODE -ne 0) {
    Write-Error "Seed DB masih kotor. Jalankan 'python sanitize_seed_db.py' terlebih dahulu."
    exit 1
}

Write-Host "[2/4] Menyusun environment variables produksi (tanpa hardcode)..."
$envPairs = @("GEMINI_API_KEY=$($env:GEMINI_API_KEY)")
foreach ($optKey in @("DATABASE_URL", "SESSION_SECRET", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GEMINI_MODEL")) {
    $val = [Environment]::GetEnvironmentVariable($optKey)
    if (-not [string]::IsNullOrWhiteSpace($val)) {
        $envPairs += "$optKey=$val"
    }
}
$envArg = ($envPairs -join ",")

Write-Host "[3/4] Menjalankan gcloud run deploy ke $Region ($ProjectId)..."
gcloud config set project $ProjectId
gcloud run deploy $ServiceName `
    --source . `
    --region $Region `
    --platform managed `
    --allow-unauthenticated `
    --memory $Memory `
    --cpu $Cpu `
    --min-instances $MinInstances `
    --max-instances $MaxInstances `
    --session-affinity `
    --set-env-vars $envArg

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[4/4] Deploy selesai! Untuk menghubungkan domain sendiri, jalankan:"
Write-Host "  gcloud beta run domain-mappings create --service $ServiceName --domain nutrisicerdas.id --region $Region"
