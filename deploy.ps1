[CmdletBinding()]
param(
    [switch]$Pull,
    [switch]$GeoDb,
    [switch]$DryRun,
    [switch]$ForceUnlock
)

$ErrorActionPreference = 'Stop'
$composeFile = 'docker-compose.yml'
$stateDir = '.deploy'
$lockDir = Join-Path $stateDir 'deploy.lock'

function Get-ComposeEnvironmentValue([string]$Name) {
    $line = (& docker compose -f $composeFile config --environment | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -First 1)
    if ($null -eq $line) { return '' }
    return $line.Substring($Name.Length + 1)
}

function Invoke-Compose([string[]]$Arguments) {
    & docker @script:composeArgs @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed: $($Arguments -join ' ')" }
}

$projectName = if ($env:STACK_NAME) { $env:STACK_NAME } else { Get-ComposeEnvironmentValue 'STACK_NAME' }
if (-not $projectName) { $projectName = 'ecosignal' }
$originalProjectName = $projectName
$projectName = (($projectName.ToLowerInvariant() -replace '[^a-z0-9_-]+', '-') -replace '^[^a-z0-9]+|[^a-z0-9]+$', '')
if (-not $projectName) { $projectName = 'ecosignal' }
if ($projectName -ne $originalProjectName) {
    Write-Host "Normalized STACK_NAME '$originalProjectName' to '$projectName' for Docker Compose"
}
$env:STACK_NAME = $projectName
$domain = if ($env:DOMAIN) { $env:DOMAIN } else { Get-ComposeEnvironmentValue 'DOMAIN' }
if (-not $domain) { $domain = 'localhost' }
$httpsValue = if ($env:ENABLE_HTTPS) { $env:ENABLE_HTTPS } else { Get-ComposeEnvironmentValue 'ENABLE_HTTPS' }
$httpsEnabled = $httpsValue -eq 'true'
$email = if ($env:EMAIL) { $env:EMAIL } else { Get-ComposeEnvironmentValue 'EMAIL' }

if ($httpsValue -notin @('true', 'false')) { throw 'ENABLE_HTTPS must be true or false' }
if ($httpsEnabled -and (($domain -eq 'localhost') -or -not $email)) {
    throw 'HTTPS requires a public DOMAIN and EMAIL for certificate issuance'
}

New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
if ($ForceUnlock -and (Test-Path $lockDir)) {
    Remove-Item -LiteralPath $lockDir -Recurse -Force
}
try {
    New-Item -ItemType Directory -Path $lockDir -ErrorAction Stop | Out-Null
} catch {
    throw "Another deployment may be running. Inspect $lockDir\owner, then use -ForceUnlock only for a stale lock."
}
Set-Content -LiteralPath (Join-Path $lockDir 'owner') -Value "pid=$PID`nhost=$env:COMPUTERNAME`nstarted_at=$([DateTime]::UtcNow.ToString('o'))" -NoNewline

try {
    $script:composeArgs = @('compose', '--project-name', $projectName, '--profile', 'production', '-f', $composeFile)
    if ($httpsEnabled) { $script:composeArgs += @('-f', 'docker-compose.https.yml') }

    $resolvedConfig = (& docker @script:composeArgs config)
    if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve Docker Compose configuration' }
    if ($resolvedConfig -match 'ecosignal-backend-dev|uvicorn.*--reload|target: 5173|published: "5173"') {
        throw 'Resolved configuration contains development runtime settings'
    }

    Write-Host "Deployment mode: $(if ($httpsEnabled) { 'HTTPS' } else { 'HTTP' })"
    Write-Host 'Resolved production services:'
    Invoke-Compose @('config', '--services')

    if ($DryRun) {
        Write-Host "Dry run succeeded: project=$projectName domain=$domain"
        return
    }

    if ($httpsEnabled) {
        & docker network inspect traefik-public *> $null
        if ($LASTEXITCODE -ne 0) { & docker network create traefik-public | Out-Null }
        & docker compose --project-name ecosignal-traefik -f docker-compose.traefik.yml up -d
        if ($LASTEXITCODE -ne 0) { throw 'Unable to start Traefik' }
    }

    $buildArgs = @('build')
    if ($Pull) { $buildArgs += '--pull' }
    Write-Host "[1/5] Building application images for $domain"
    Invoke-Compose ($buildArgs + @('backend', 'frontend'))

    $images = (& docker @script:composeArgs config --images)
    $geoDbImage = $images | Where-Object { $_ -match 'geo_db' } | Select-Object -First 1
    $geoDbExists = $false
    if ($geoDbImage) {
        & docker image inspect $geoDbImage *> $null
        $geoDbExists = $LASTEXITCODE -eq 0
    }
    if ($GeoDb -or -not $geoDbImage -or -not $geoDbExists) {
        Write-Host '[2/5] Building geo_db image'
        Invoke-Compose ($buildArgs + @('geo_db'))
    } else {
        Write-Host '[2/5] Reusing existing geo_db image'
    }

    Write-Host '[3/5] Starting dependencies'
    Invoke-Compose @('up', '-d', '--no-build', '--wait', 'db', 'geo_db', 'redis', 'rabbitmq')
    Write-Host '[4/5] Applying database setup once'
    Invoke-Compose @('run', '--rm', '--no-deps', '-e', 'SKIP_PRESTART=true', 'backend', 'bash', '/app/scripts/prestart.sh')
    Write-Host '[5/5] Starting application services'
    Invoke-Compose @('up', '-d', '--no-build', '--wait', '--remove-orphans', 'backend', 'worker', 'worker-analysis', 'frontend')

    Write-Host "Deployment succeeded: $domain"
    Invoke-Compose @('ps')
} catch {
    try { Invoke-Compose @('ps') } catch {}
    try { Invoke-Compose @('logs', '--tail=200', 'backend', 'worker', 'worker-analysis', 'frontend') } catch {}
    throw
} finally {
    Remove-Item -LiteralPath $lockDir -Recurse -Force -ErrorAction SilentlyContinue
}
