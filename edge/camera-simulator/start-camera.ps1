param(
    [Parameter(Mandatory = $true)]
    [string]$VideoPath,

    [string]$StreamPath = "camera1",
    [string]$PublisherUser = "publisher",

    [Parameter(Mandatory = $true)]
    [string]$PublisherPassword,

    [string]$RtspHost = "127.0.0.1",
    [int]$RtspPort = 8554
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $VideoPath)) {
    throw "Video file not found: $VideoPath"
}

$escapedUser = [Uri]::EscapeDataString($PublisherUser)
$escapedPassword = [Uri]::EscapeDataString($PublisherPassword)
$authority = "{0}:{1}@{2}:{3}" -f `
    $escapedUser, $escapedPassword, $RtspHost, $RtspPort
$target = "rtsp://$authority/$StreamPath"

& ffmpeg `
    -re `
    -stream_loop -1 `
    -i $VideoPath `
    -an `
    -c:v libx264 `
    -preset veryfast `
    -tune zerolatency `
    -f rtsp `
    -rtsp_transport tcp `
    $target

if ($LASTEXITCODE -ne 0) {
    throw "FFmpeg exited with code $LASTEXITCODE"
}
