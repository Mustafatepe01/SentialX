param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ProjectId,
    [string]$Region = "europe-west1",
    [string]$GeminiSecret = "gemini-api-key",
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ReportBucket,
    [string]$RagServiceName = "sentialx-rag",
    [string]$ReportServiceName = "sentialx-report"
)

$ErrorActionPreference = "Stop"

$ragDir = Join-Path $PSScriptRoot "rag-service"
$reportDir = Join-Path $PSScriptRoot "report-service"
$ragServiceAccountId = "sentialx-rag-runtime"
$reportServiceAccountId = "sentialx-report-runtime"
$ragServiceAccount = "$ragServiceAccountId@$ProjectId.iam.gserviceaccount.com"
$reportServiceAccount = "$reportServiceAccountId@$ProjectId.iam.gserviceaccount.com"

function Ensure-ServiceAccount([string]$accountId, [string]$displayName) {
    $existing = & gcloud iam service-accounts list `
        --project $ProjectId `
        --filter "email:$accountId@$ProjectId.iam.gserviceaccount.com" `
        --format "value(email)"

    if (-not $existing) {
        & gcloud iam service-accounts create $accountId `
            --project $ProjectId `
            --display-name $displayName
    }
}

& gcloud config set project $ProjectId
& gcloud services enable `
    run.googleapis.com `
    cloudbuild.googleapis.com `
    artifactregistry.googleapis.com `
    secretmanager.googleapis.com

Ensure-ServiceAccount $ragServiceAccountId "SentialX RAG runtime"
Ensure-ServiceAccount $reportServiceAccountId "SentialX Report runtime"

foreach ($member in @($ragServiceAccount, $reportServiceAccount)) {
    & gcloud secrets add-iam-policy-binding $GeminiSecret `
        --project $ProjectId `
        --member "serviceAccount:$member" `
        --role "roles/secretmanager.secretAccessor"
}

& gcloud storage buckets add-iam-policy-binding "gs://$ReportBucket" `
    --member "serviceAccount:$reportServiceAccount" `
    --role "roles/storage.objectAdmin"

Push-Location $ragDir
try {
    & gcloud run deploy $RagServiceName `
        --project $ProjectId `
        --source . `
        --region $Region `
        --no-allow-unauthenticated `
        --service-account $ragServiceAccount `
        --memory 1Gi `
        --cpu 1 `
        --min-instances 0 `
        --max-instances 2 `
        --concurrency 4 `
        --timeout 300 `
        --set-env-vars "INDEX_PATH=data/sentialx_isg_kaynak_url_fixed_structure.json,LLM_MODEL=gemini/gemini-3-flash-preview" `
        --set-secrets "GEMINI_API_KEY=$GeminiSecret`:latest" `
        --quiet
}
finally {
    Pop-Location
}

$ragUrl = & gcloud run services describe $RagServiceName `
    --project $ProjectId `
    --region $Region `
    --format "value(status.url)"

if (-not $ragUrl) {
    throw "RAG servis URL'si alınamadı"
}

& gcloud run services add-iam-policy-binding $RagServiceName `
    --project $ProjectId `
    --region $Region `
    --member "serviceAccount:$reportServiceAccount" `
    --role "roles/run.invoker"

Push-Location $reportDir
try {
    & gcloud run deploy $ReportServiceName `
        --project $ProjectId `
        --source . `
        --region $Region `
        --no-allow-unauthenticated `
        --service-account $reportServiceAccount `
        --memory 1Gi `
        --cpu 1 `
        --min-instances 0 `
        --max-instances 2 `
        --concurrency 4 `
        --timeout 300 `
        --set-env-vars "MOCK_MODE=0,GEMINI_MODEL=gemini/gemini-3-flash-preview,QUEUE_BACKEND=file,GCS_ENABLED=1,GCS_BUCKET=$ReportBucket,RAG_SERVICE_URL=$ragUrl,RAG_AUTH_MODE=google_id_token" `
        --set-secrets "GEMINI_API_KEY=$GeminiSecret`:latest" `
        --quiet
}
finally {
    Pop-Location
}

$reportUrl = & gcloud run services describe $ReportServiceName `
    --project $ProjectId `
    --region $Region `
    --format "value(status.url)"

Write-Host "RAG Service:    $ragUrl"
Write-Host "Report Service: $reportUrl"
Write-Host "Report Service, RAG Service'i OIDC ile çağırmaya yetkilendirildi."
Write-Host "Cloud Run'da /report ve /report/pdf uçlarını kullanın."
Write-Host "/report/queue dosya tabanlı olduğu için üretim kuyruğu olarak kullanılmamalıdır."
