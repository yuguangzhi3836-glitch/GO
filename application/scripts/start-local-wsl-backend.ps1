[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$applicationRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $applicationRoot 'docker-compose.staging.yml'
$localComposeFile = Join-Path $applicationRoot 'docker-compose.local.yml'
$projectName = 'go-hotel-staging'
$dockerCommand = Get-Command 'docker.exe' -ErrorAction SilentlyContinue

if (-not $dockerCommand) {
    throw 'docker.exe was not found. Install Docker Desktop with its WSL2 engine enabled.'
}
if (-not (Test-Path -LiteralPath $composeFile -PathType Leaf)) {
    throw "Compose file not found: $composeFile"
}
if (-not (Test-Path -LiteralPath $localComposeFile -PathType Leaf)) {
    throw "Local Compose overrides not found: $localComposeFile"
}

function Test-DockerEngine {
    & $dockerCommand.Source info --format '{{.ServerVersion}}' *> $null
    return $LASTEXITCODE -eq 0
}

if (-not (Test-DockerEngine)) {
    $desktopPath = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (-not (Test-Path -LiteralPath $desktopPath -PathType Leaf)) {
        throw 'Docker Desktop is not installed at the standard path and the Docker engine is not running.'
    }

    Write-Host 'Starting Docker Desktop (WSL2 engine)...'
    Start-Process -FilePath $desktopPath -WindowStyle Hidden
    $engineDeadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $engineDeadline) {
        Start-Sleep -Seconds 5
        if (Test-DockerEngine) { break }
    }
    if (-not (Test-DockerEngine)) {
        throw 'Docker Desktop did not become ready within 3 minutes.'
    }
}

$services = @(
    'api',
    'outbox-worker',
    'recovery-worker',
    'reconciliation-worker',
    'judgment-worker',
    'mobile-engagement-worker',
    'mobile-push-worker',
    'mobile-push-receipt-worker',
    'regional-hotel-build-worker'
)
$composeArguments = @(
    'compose', '--project-name', $projectName,
    '--file', $composeFile,
    '--file', $localComposeFile,
    'up', '--build', '--detach'
) + $services

Write-Host 'Building and starting the local backend and workers...'
& $dockerCommand.Source @composeArguments
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose failed with exit code $LASTEXITCODE."
}

$healthUrl = 'http://127.0.0.1:8000/health'
$healthDeadline = (Get-Date).AddMinutes(3)
$healthy = $false
while ((Get-Date) -lt $healthDeadline) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            Write-Host "Backend is healthy: $healthUrl"
            Write-Host $response.Content
            $healthy = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 3
    }
}

& $dockerCommand.Source compose '--project-name' $projectName '--file' $composeFile '--file' $localComposeFile 'ps'
if (-not $healthy) {
    throw "Backend did not become healthy at $healthUrl within 3 minutes. Inspect the Docker Compose logs."
}
