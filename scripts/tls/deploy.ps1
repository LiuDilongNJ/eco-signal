$script:tlsImage = 'ecosignal-tls-tools:local'
$script:tlsPending = $false

function Invoke-Docker([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker operation failed: $($Arguments[0])" }
}

function Invoke-TlsSource([string]$Action) {
    Invoke-Docker @('run', '--rm', '--network', 'none',
        '--mount', "type=bind,source=$tlsCertFile,target=/source/cert.pem,readonly",
        '--mount', "type=bind,source=$tlsKeyFile,target=/source/key.pem,readonly",
        '--mount', "type=bind,source=$((Get-Location).Path)/.deploy/tls,target=/state",
        $script:tlsImage, $Action, '--domain', $domain)
}

function Get-FrontendId {
    $id = & docker @script:composeArgs ps -q frontend
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect frontend' }
    return $id
}

function Test-Endpoint([string]$Phase) {
    $port = '443'
    $timeout = '30'
    $mountArgs = @()
    if ($httpsEnabled -and $httpsMode -eq 'letsencrypt') {
        $target = & docker compose --project-name ecosignal-traefik -f docker-compose.traefik.yml ps -q traefik
        if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect Traefik' }
        $timeout = '180'
    } else {
        $target = Get-FrontendId
        if ($httpsEnabled) {
            $mountArgs = @('--mount', "type=bind,source=$((Get-Location).Path)/.deploy/tls,target=/state,readonly")
        } else { $port = '80' }
    }
    if (-not $target) { throw 'HTTPS/HTTP entry container is not running' }
    $probeArgs = @('probe', '--domain', $domain, '--port', $port, '--timeout', $timeout)
    if (-not $httpsEnabled) { $probeArgs += '--http' }
    if ($httpsEnabled -and $httpsMode -eq 'static') { $probeArgs += @('--pin', '--cert', '/state/cert.pem') }
    if ($Phase -eq 'application') { $probeArgs += @('--path', '/', '--path', '/api/v1/health') }
    Invoke-Docker (@('run', '--rm', '--network', "container:$target") + $mountArgs + @($script:tlsImage) + $probeArgs)
}

function Restore-Tls {
    Invoke-Docker @('run', '--rm', '--network', 'none', '--mount', "type=bind,source=$((Get-Location).Path)/.deploy/tls,target=/state",
        $script:tlsImage, 'restore', '--domain', $domain)
    if (Get-FrontendId) {
        Invoke-Compose @('exec', '-T', 'frontend', 'nginx', '-t')
        Invoke-Compose @('exec', '-T', 'frontend', 'nginx', '-s', 'reload')
        Test-Endpoint 'tls'
    }
}

function Update-Tls {
    $target = Get-FrontendId
    if (-not $target) { throw 'Certificate reload requires a running static HTTPS frontend' }
    $details = & docker inspect $target | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect frontend' }
    if ($details[0].Config.Labels.'ecosignal.tls-mode' -ne 'static' -or $details[0].Config.Labels.'ecosignal.domain' -ne $domain) {
        throw 'Certificate reload requires a running static HTTPS frontend for DOMAIN'
    }
    Invoke-TlsSource 'install'
    $script:tlsPending = $true
    Invoke-Compose @('exec', '-T', 'frontend', 'nginx', '-t')
    Invoke-Compose @('exec', '-T', 'frontend', 'nginx', '-s', 'reload')
    Test-Endpoint 'tls'
    $script:tlsPending = $false
    Write-Host 'TLS certificate reloaded and verified without restarting the frontend'
}

function Initialize-Entrypoint {
    $target = & docker ps -aq --filter label=com.docker.compose.project=ecosignal-traefik --filter label=com.docker.compose.service=traefik
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect entrypoint' }
    if ($target) {
        $details = & docker inspect $target | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or $details.Count -ne 1) { throw 'Unable to identify entrypoint owner' }
        $labels = $details[0].Config.Labels
        if ($labels.'com.docker.compose.project.working_dir' -ne (Get-Location).Path) {
            throw 'Existing Traefik belongs to another deployment; port handoff refused'
        }
    }
    if ($httpsEnabled -and $httpsMode -eq 'letsencrypt') {
        $frontend = Get-FrontendId
        if ($frontend) {
            $bindings = & docker inspect -f '{{json .HostConfig.PortBindings}}' $frontend
            if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect frontend ports' }
            if ($bindings -match '"HostPort":"(80|443)"') { Invoke-Docker @('stop', $frontend) }
        }
        & docker network inspect traefik-public *> $null
        if ($LASTEXITCODE -ne 0) { Invoke-Docker @('network', 'create', 'traefik-public') }
        Invoke-Docker @('compose', '--project-name', 'ecosignal-traefik', '-f', 'docker-compose.traefik.yml', 'up', '-d')
    } elseif ($target) { Invoke-Docker @('stop', $target) }
}
