param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$FrameBucket,

    [string]$Region = "europe-west1",
    [string]$ServiceName = "sentialx-frame-worker",
    [string]$RuntimeServiceAccount = "sentialx-worker-sa",
    [string]$PushServiceAccount = "sentialx-pubsub-push",
    [string]$EdgeServiceAccount = "sentialx-edge",
    [string]$SchedulerServiceAccount = "sentialx-scheduler",
    [string]$FramesTopic = "sentialx-frames",
    [string]$FireTopic = "fire-alerts",
    [string]$DeadLetterTopic = "sentialx-frames-dead-letter",
    [string]$DeadLetterSubscription = "sentialx-frames-dead-letter-sub",
    [string]$Subscription = "sentialx-frame-worker-push",
    [string]$PpeShiftJob = "sentialx-ppe-shift-report",
    [string]$DatabaseSecret = "db-url",
    [string]$SupabaseSecret = "supabase-config",
    [string]$CloudSqlInstance = "sentialx-db"
)

$ErrorActionPreference = "Stop"
$sourceDir = Join-Path $PSScriptRoot "frame-worker"
$runtimeEmail = "$RuntimeServiceAccount@$ProjectId.iam.gserviceaccount.com"
$pushEmail = "$PushServiceAccount@$ProjectId.iam.gserviceaccount.com"
$edgeEmail = "$EdgeServiceAccount@$ProjectId.iam.gserviceaccount.com"
$schedulerEmail = "$SchedulerServiceAccount@$ProjectId.iam.gserviceaccount.com"
$cloudSqlConnection = "$ProjectId`:$Region`:$CloudSqlInstance"

function Ensure-ServiceAccount([string]$AccountId, [string]$DisplayName) {
    $email = & gcloud iam service-accounts list `
        --project $ProjectId `
        --filter "email:$AccountId@$ProjectId.iam.gserviceaccount.com" `
        --format "value(email)"
    if (-not $email) {
        & gcloud iam service-accounts create $AccountId `
            --project $ProjectId `
            --display-name $DisplayName
    }
}

function Ensure-Topic([string]$TopicName) {
    $existing = & gcloud pubsub topics list `
        --project $ProjectId `
        --filter "name:$TopicName" `
        --format "value(name)"
    if (-not $existing) {
        & gcloud pubsub topics create $TopicName --project $ProjectId
    }
}

& gcloud services enable `
    run.googleapis.com `
    cloudbuild.googleapis.com `
    pubsub.googleapis.com `
    secretmanager.googleapis.com `
    sqladmin.googleapis.com `
    cloudscheduler.googleapis.com `
    --project $ProjectId

Ensure-ServiceAccount $RuntimeServiceAccount "SentialX frame worker runtime"
Ensure-ServiceAccount $PushServiceAccount "SentialX PubSub push identity"
Ensure-ServiceAccount $EdgeServiceAccount "SentialX edge identity"
Ensure-ServiceAccount $SchedulerServiceAccount "SentialX scheduler identity"
Ensure-Topic $FramesTopic
Ensure-Topic $FireTopic
Ensure-Topic $DeadLetterTopic

$existingDeadLetterSubscription = & gcloud pubsub subscriptions list `
    --project $ProjectId `
    --filter "name:$DeadLetterSubscription" `
    --format "value(name)"
if (-not $existingDeadLetterSubscription) {
    & gcloud pubsub subscriptions create $DeadLetterSubscription `
        --project $ProjectId `
        --topic $DeadLetterTopic `
        --message-retention-duration 7d
}

foreach ($secret in @($DatabaseSecret, $SupabaseSecret)) {
    & gcloud secrets add-iam-policy-binding $secret `
        --project $ProjectId `
        --member "serviceAccount:$runtimeEmail" `
        --role "roles/secretmanager.secretAccessor"
}

& gcloud storage buckets add-iam-policy-binding "gs://$FrameBucket" `
    --member "serviceAccount:$runtimeEmail" `
    --role "roles/storage.objectUser"

& gcloud storage buckets add-iam-policy-binding "gs://$FrameBucket" `
    --member "serviceAccount:$edgeEmail" `
    --role "roles/storage.objectCreator"

& gcloud pubsub topics add-iam-policy-binding $FramesTopic `
    --project $ProjectId `
    --member "serviceAccount:$edgeEmail" `
    --role "roles/pubsub.publisher"

& gcloud pubsub topics add-iam-policy-binding $FireTopic `
    --project $ProjectId `
    --member "serviceAccount:$runtimeEmail" `
    --role "roles/pubsub.publisher"

& gcloud projects add-iam-policy-binding $ProjectId `
    --member "serviceAccount:$runtimeEmail" `
    --role "roles/cloudsql.client" `
    --condition None

$ppeUrl = & gcloud run services describe ppe-detection `
    --project $ProjectId --region $Region --format "value(status.url)"
$fireUrl = & gcloud run services describe fire-detection `
    --project $ProjectId --region $Region --format "value(status.url)"
$vlmUrl = & gcloud run services describe vlm-service `
    --project $ProjectId --region $Region --format "value(status.url)"
$reportUrl = & gcloud run services describe sentialx-report `
    --project $ProjectId --region $Region --format "value(status.url)"

foreach ($analysisService in @(
    "ppe-detection",
    "fire-detection",
    "vlm-service",
    "sentialx-report"
)) {
    & gcloud run services add-iam-policy-binding $analysisService `
        --project $ProjectId `
        --region $Region `
        --member "serviceAccount:$runtimeEmail" `
        --role "roles/run.invoker"
}

Push-Location $sourceDir
try {
    & gcloud run deploy $ServiceName `
        --project $ProjectId `
        --source . `
        --region $Region `
        --no-allow-unauthenticated `
        --service-account $runtimeEmail `
        --add-cloudsql-instances $cloudSqlConnection `
        --memory 1Gi `
        --cpu 1 `
        --max-instances 3 `
        --concurrency 4 `
        --timeout 600 `
        --set-env-vars "PROJECT_ID=$ProjectId,PPE_URL=$ppeUrl/detect,FIRE_URL=$fireUrl/detect,VLM_URL=$vlmUrl/analyze,REPORT_URL=$reportUrl/report,FIRE_TOPIC=$FireTopic,LOCAL_TIMEZONE=Europe/Istanbul" `
        --set-secrets "DB_URL=$DatabaseSecret`:latest,SUPABASE_CONFIG=$SupabaseSecret`:latest" `
        --quiet
}
finally {
    Pop-Location
}

$workerUrl = & gcloud run services describe $ServiceName `
    --project $ProjectId --region $Region --format "value(status.url)"

foreach ($invoker in @($pushEmail, $edgeEmail, $schedulerEmail)) {
    & gcloud run services add-iam-policy-binding $ServiceName `
        --project $ProjectId `
        --region $Region `
        --member "serviceAccount:$invoker" `
        --role "roles/run.invoker"
}

$ppeShiftUri = "$workerUrl/internal/ppe-shift-reports/run"
$existingPpeShiftJob = & gcloud scheduler jobs list `
    --project $ProjectId `
    --location $Region `
    --filter "name:$PpeShiftJob" `
    --format "value(name)"
$schedulerArgs = @(
    "--project", $ProjectId,
    "--location", $Region,
    "--schedule", "5 0,8,16 * * *",
    "--time-zone", "Europe/Istanbul",
    "--uri", $ppeShiftUri,
    "--http-method", "POST",
    "--oidc-service-account-email", $schedulerEmail,
    "--oidc-token-audience", $workerUrl,
    "--attempt-deadline", "600s",
    "--max-retry-attempts", "3",
    "--min-backoff", "30s",
    "--max-backoff", "600s"
)
if ($existingPpeShiftJob) {
    & gcloud scheduler jobs update http $PpeShiftJob @schedulerArgs
}
else {
    & gcloud scheduler jobs create http $PpeShiftJob @schedulerArgs
}

$projectNumber = & gcloud projects describe $ProjectId `
    --format "value(projectNumber)"
$pubsubAgent = "service-$projectNumber@gcp-sa-pubsub.iam.gserviceaccount.com"

& gcloud iam service-accounts add-iam-policy-binding $pushEmail `
    --project $ProjectId `
    --member "serviceAccount:$pubsubAgent" `
    --role "roles/iam.serviceAccountTokenCreator"

& gcloud pubsub topics add-iam-policy-binding $DeadLetterTopic `
    --project $ProjectId `
    --member "serviceAccount:$pubsubAgent" `
    --role "roles/pubsub.publisher"

$existingSubscription = & gcloud pubsub subscriptions list `
    --project $ProjectId `
    --filter "name:$Subscription" `
    --format "value(name)"
$subscriptionArgs = @(
    "--project", $ProjectId,
    "--push-endpoint", "$workerUrl/pubsub/frame",
    "--push-auth-service-account", $pushEmail,
    "--ack-deadline", "600",
    "--min-retry-delay", "10s",
    "--max-retry-delay", "600s",
    "--dead-letter-topic", $DeadLetterTopic,
    "--max-delivery-attempts", "5"
)
if ($existingSubscription) {
    & gcloud pubsub subscriptions update $Subscription @subscriptionArgs
}
else {
    & gcloud pubsub subscriptions create $Subscription `
        --topic $FramesTopic `
        @subscriptionArgs
}

& gcloud pubsub subscriptions add-iam-policy-binding $Subscription `
    --project $ProjectId `
    --member "serviceAccount:$pubsubAgent" `
    --role "roles/pubsub.subscriber"

Write-Host "Frame worker: $workerUrl"
Write-Host "Push subscription: $Subscription"
Write-Host "Dead-letter subscription: $DeadLetterSubscription"
Write-Host "PPE shift scheduler: $PpeShiftJob"
