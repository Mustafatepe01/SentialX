param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ProjectId,

    [string]$Region = "europe-west1",
    [string]$ServiceName = "sentialx-fire-notifier",
    [string]$Topic = "fire-alerts",
    [string]$Subscription = "sentialx-fire-alerts-push",
    [string]$PushServiceAccount = "sentialx-pubsub-push"
)

$ErrorActionPreference = "Stop"
$sourceDir = Join-Path $PSScriptRoot "fire-notifier"
$pushEmail = "$PushServiceAccount@$ProjectId.iam.gserviceaccount.com"

Push-Location $sourceDir
try {
    & gcloud run deploy $ServiceName `
        --project $ProjectId `
        --source . `
        --region $Region `
        --no-allow-unauthenticated `
        --memory 256Mi `
        --cpu 1 `
        --max-instances 2 `
        --concurrency 20 `
        --timeout 60 `
        --quiet
}
finally {
    Pop-Location
}

$serviceUrl = & gcloud run services describe $ServiceName `
    --project $ProjectId `
    --region $Region `
    --format "value(status.url)"

& gcloud run services add-iam-policy-binding $ServiceName `
    --project $ProjectId `
    --region $Region `
    --member "serviceAccount:$pushEmail" `
    --role "roles/run.invoker"

$existing = & gcloud pubsub subscriptions list `
    --project $ProjectId `
    --filter "name:$Subscription" `
    --format "value(name)"
$subscriptionArgs = @(
    "--project", $ProjectId,
    "--push-endpoint", "$serviceUrl/pubsub/fire",
    "--push-auth-service-account", $pushEmail,
    "--ack-deadline", "60",
    "--min-retry-delay", "10s",
    "--max-retry-delay", "300s"
)
if ($existing) {
    & gcloud pubsub subscriptions update $Subscription @subscriptionArgs
}
else {
    & gcloud pubsub subscriptions create $Subscription `
        --topic $Topic `
        @subscriptionArgs
}

Write-Host "Fire notifier: $serviceUrl"
Write-Host "Fire subscription: $Subscription"
