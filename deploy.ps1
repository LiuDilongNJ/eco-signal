[CmdletBinding()]
param(
    [switch]$ReloadCerts,
    [switch]$Pull,
    [switch]$GeoDb,
    [switch]$DryRun,
    [switch]$ForceUnlock,
    [ValidateSet('on', 'off', 'status')]
    [string]$Maintenance
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$composeFile = 'docker-compose.yml'
$stateDir = '.deploy'
$lockDir = Join-Path $stateDir 'deploy.lock'
$script:maintenanceStartedByDeploy = $false

function Get-ComposeEnvironmentValue([string]$Name) {
    $environment = & docker compose -f $composeFile config --environment
    if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve deployment environment' }
    $line = ($environment | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -First 1)
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
$httpsMode = if ($env:HTTPS_MODE) { $env:HTTPS_MODE } else { Get-ComposeEnvironmentValue 'HTTPS_MODE' }
if ($httpsMode) { $httpsMode = $httpsMode.ToLowerInvariant() } else { $httpsMode = 'letsencrypt' }
$email = if ($env:EMAIL) { $env:EMAIL } else { Get-ComposeEnvironmentValue 'EMAIL' }
$tlsCertFile = if ($env:TLS_CERT_FILE) { $env:TLS_CERT_FILE } else { Get-ComposeEnvironmentValue 'TLS_CERT_FILE' }
$tlsKeyFile = if ($env:TLS_KEY_FILE) { $env:TLS_KEY_FILE } else { Get-ComposeEnvironmentValue 'TLS_KEY_FILE' }
$mediaStorageMode = if ($env:MEDIA_STORAGE_MODE) { $env:MEDIA_STORAGE_MODE } else { Get-ComposeEnvironmentValue 'MEDIA_STORAGE_MODE' }
if (-not $mediaStorageMode) { $mediaStorageMode = 'managed' }

if ($domain -notmatch '^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$') { throw 'DOMAIN must be a hostname without a scheme, port or path' }
if ($httpsValue -notin @('true', 'false')) { throw 'ENABLE_HTTPS must be true or false' }
if ($httpsEnabled) {
    if ($httpsMode -notin @('letsencrypt', 'static')) { throw "HTTPS_MODE must be 'letsencrypt' or 'static'" }
    if ($domain -eq 'localhost') { throw "HTTPS requires a valid public DOMAIN (cannot be 'localhost')" }
    if ($httpsMode -eq 'letsencrypt') {
        if (-not $email) { throw "Let's Encrypt HTTPS requires EMAIL as the ACME account contact" }
    } elseif ($httpsMode -eq 'static' -and -not $Maintenance) {
        if (-not $tlsCertFile -or -not $tlsKeyFile) { throw 'Static HTTPS mode requires TLS_CERT_FILE and TLS_KEY_FILE in .env' }
        if (-not (Test-Path -LiteralPath $tlsCertFile -PathType Leaf)) { throw "TLS certificate file not found: $tlsCertFile" }
        if (-not (Test-Path -LiteralPath $tlsKeyFile -PathType Leaf)) { throw "TLS private key file not found: $tlsKeyFile" }
        $tlsCertFile = (Resolve-Path -LiteralPath $tlsCertFile).Path
        $tlsKeyFile = (Resolve-Path -LiteralPath $tlsKeyFile).Path
    }
}
if ($mediaStorageMode -notin @('managed', 'direct-mount')) {
    throw 'MEDIA_STORAGE_MODE must be managed or direct-mount'
}

$maintenanceDir = 'maintenance'
$maintenanceFlag = Join-Path $maintenanceDir 'maintenance.flag'
$maintenanceCompose = 'docker-compose.maintenance.yml'

function Enable-Maintenance {
    New-Item -ItemType Directory -Path $maintenanceDir -Force | Out-Null
    New-Item -ItemType File -Path $maintenanceFlag -Force | Out-Null
    if ($httpsEnabled -and $httpsMode -eq 'letsencrypt') {
        & docker network inspect traefik-public *> $null
        if ($LASTEXITCODE -ne 0) { & docker network create traefik-public | Out-Null }
        $env:STACK_NAME = $projectName
        $env:DOMAIN = $domain
        & docker compose --project-name $projectName -f $maintenanceCompose up -d
        if ($LASTEXITCODE -ne 0) { throw 'Unable to start maintenance container' }
    }
    Write-Host 'Maintenance mode is now ACTIVE.'
}

function Disable-Maintenance {
    if ($httpsEnabled -and $httpsMode -eq 'letsencrypt') {
        $env:STACK_NAME = $projectName
        $env:DOMAIN = $domain
        Invoke-Docker @('compose', '--project-name', $projectName, '-f', $maintenanceCompose, 'stop', 'maintenance')
        Invoke-Docker @('compose', '--project-name', $projectName, '-f', $maintenanceCompose, 'rm', '-f', 'maintenance')
    }
    if (Test-Path $maintenanceFlag) { Remove-Item -LiteralPath $maintenanceFlag -Force }
    Write-Host 'Maintenance mode is now DISABLED.'
}

function Get-MaintenanceStatus {
    $active = Test-Path $maintenanceFlag
    if ($httpsEnabled -and $httpsMode -eq 'letsencrypt') {
        $running = (& docker compose --project-name $projectName -f $maintenanceCompose ps --services --filter "status=running" 2>$null)
        if ($running -match 'maintenance') { $active = $true }
    }
    if ($active) {
        Write-Host 'Maintenance mode: ACTIVE'
    } else {
        Write-Host 'Maintenance mode: INACTIVE'
    }
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

. ./scripts/tls/deploy.ps1
try {
    if ($ReloadCerts -and (-not $httpsEnabled -or $httpsMode -ne 'static' -or $Maintenance -or $DryRun -or $Pull -or $GeoDb)) {
        throw '-ReloadCerts requires static HTTPS and cannot be combined with deployment actions'
    }
    if ($DryRun -and $Maintenance) { throw '-DryRun cannot be combined with -Maintenance' }
    $env:DOMAIN = $domain
    $env:STACK_NAME = $projectName
    $env:EMAIL = $email
    if ($Maintenance) {
        switch ($Maintenance) {
            'on' { Enable-Maintenance }
            'off' { Disable-Maintenance }
            'status' { Get-MaintenanceStatus }
        }
        return
    }

    $script:composeArgs = @('compose', '--project-name', $projectName, '--profile', 'production', '-f', $composeFile)
    if ($mediaStorageMode -eq 'direct-mount') { $script:composeArgs += @('-f', 'docker-compose.media-direct.yml') }
    if ($httpsEnabled) {
        if ($httpsMode -eq 'static') {
            $script:composeArgs += @('-f', 'docker-compose.https-static.yml')
        } else {
            $script:composeArgs += @('-f', 'docker-compose.https.yml')
        }
    }

    $resolvedConfig = (& docker @script:composeArgs config)
    if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve Docker Compose configuration' }
    if ($resolvedConfig -match 'ecosignal-backend-dev|uvicorn.*--reload|target: 5173|published: "5173"') {
        throw 'Resolved configuration contains development runtime settings'
    }

    Write-Host "Deployment mode: $(if ($httpsEnabled) { "HTTPS ($httpsMode)" } else { 'HTTP' }), media=$mediaStorageMode"
    Write-Host 'Resolved production services:'
    Invoke-Compose @('config', '--services')

    if ($httpsEnabled -and $httpsMode -eq 'letsencrypt') {
        Invoke-Docker @('compose', '--project-name', 'ecosignal-traefik', '-f', 'docker-compose.traefik.yml', 'config', '-q')
        Invoke-Docker @('compose', '--project-name', $projectName, '-f', $maintenanceCompose, 'config', '-q')
    }
    if (-not $DryRun -or ($httpsEnabled -and $httpsMode -eq 'static')) {
        Invoke-Docker @('build', '-q', '-t', $script:tlsImage, 'scripts/tls')
    }
    if ($httpsEnabled -and $httpsMode -eq 'static') {
        New-Item -ItemType Directory -Path "$stateDir/tls" -Force | Out-Null
        Invoke-TlsSource 'validate'
    }
    if ($DryRun) {
        Write-Host "Dry run succeeded: project=$projectName domain=$domain"
        return
    }
    if ($ReloadCerts) { Update-Tls; return }

    Write-Host "[0/5] Enabling maintenance mode for $domain"
    New-Item -ItemType File -Path $maintenanceFlag -Force | Out-Null
    $script:maintenanceStartedByDeploy = $true

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

    Initialize-Entrypoint
    if ($httpsEnabled -and $httpsMode -eq 'static') {
        Invoke-TlsSource 'install'
        $script:tlsPending = $true
    }
    Enable-Maintenance

    Write-Host '[3/5] Starting dependencies'
    Invoke-Compose @('up', '-d', '--no-build', '--wait', 'db', 'geo_db', 'redis', 'rabbitmq')
    Write-Host '[4/5] Applying database setup once'
    Invoke-Compose @('run', '--rm', '--no-deps', '-e', 'SKIP_PRESTART=true', 'backend', 'bash', '/app/scripts/prestart.sh')
    Write-Host '[5/5] Starting application services'
    Invoke-Compose @('up', '-d', '--no-build', '--wait', 'backend', 'worker', 'worker-analysis', 'frontend')

    Invoke-Compose @('exec', '-T', 'frontend', 'nginx', '-t')
    Invoke-Compose @('exec', '-T', 'frontend', 'nginx', '-s', 'reload')
    Test-Endpoint 'tls'
    $script:tlsPending = $false
    Write-Host "Disabling maintenance mode for $domain"
    Disable-Maintenance
    try { Test-Endpoint 'application' } catch { Enable-Maintenance; throw }
    $script:maintenanceStartedByDeploy = $false

    Write-Host "Deployment succeeded: $domain"
    Invoke-Compose @('ps')
} catch {
    if ($httpsEnabled -and $httpsMode -eq 'letsencrypt') {
        & docker compose --project-name ecosignal-traefik -f docker-compose.traefik.yml logs --tail=100
    }
    if ($script:maintenanceStartedByDeploy) {
        Write-Host ""
        Write-Host "================================================================="
        Write-Host "Deployment failed or was interrupted! Maintenance mode remains ACTIVE."
        Write-Host "To disable maintenance mode manually, run:"
        Write-Host "  .\deploy.ps1 -Maintenance off"
        Write-Host "================================================================="
    }
    try { Invoke-Compose @('ps') } catch {}
    try { Invoke-Compose @('logs', '--tail=200', 'backend', 'worker', 'worker-analysis', 'frontend') } catch {}
    throw
} finally {
    if ($script:tlsPending) {
        try { Restore-Tls } catch { Write-Warning "TLS rollback failed: $_" }
    }
    Remove-Item -LiteralPath $lockDir -Recurse -Force -ErrorAction SilentlyContinue
}
