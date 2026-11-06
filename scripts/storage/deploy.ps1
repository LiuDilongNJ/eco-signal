function Test-BuildSpace {
    $dockerRoot = (& docker info --format '{{.DockerRootDir}}')
    if ($LASTEXITCODE -ne 0 -or -not $dockerRoot) { throw 'Unable to locate Docker storage' }
    $capacity = (& docker run --rm --network none --mount "type=bind,source=$dockerRoot,target=/docker,readonly" alpine:3.22 sh -c 'df -Pk /docker | tail -1')
    if ($LASTEXITCODE -ne 0 -or -not $capacity) { throw 'Unable to read Docker filesystem capacity' }
    $parts = ($capacity.Trim() -split '\s+')
    [long]$totalKiB = 0
    [long]$freeKiB = 0
    if ($parts.Count -lt 4 -or -not [long]::TryParse($parts[1], [ref]$totalKiB) -or -not [long]::TryParse($parts[3], [ref]$freeKiB) -or $totalKiB -le 0) {
        throw 'Invalid Docker filesystem capacity'
    }
    $reserveKiB = [Math]::Max(5242880, [Math]::Floor($totalKiB / 10))
    Write-Host "Docker storage: total=$totalKiB KiB free=$freeKiB KiB required=$reserveKiB KiB"
    if ($freeKiB -lt $reserveKiB) { throw 'Insufficient Docker storage; release space before building' }
}

function Clear-DeploymentStorage {
    try {
        $imageHelp = (& docker image prune --help 2>&1) -join "`n"
        if ($LASTEXITCODE -eq 0 -and $imageHelp.Contains('--filter')) {
            & docker image prune --force --filter "label=org.ecosignal.project=$projectName"
            if ($LASTEXITCODE -ne 0) { Write-Warning 'Project image cleanup failed' }
        } else { Write-Warning 'Filtered image cleanup is unsupported; skipping' }
        if ($PruneBuildCache) {
            Write-Warning 'Build cache cleanup affects this Docker builder, including other projects'
            $builderHelp = (& docker builder prune --help 2>&1) -join "`n"
            if ($LASTEXITCODE -eq 0 -and $builderHelp.Contains('--keep-storage')) {
                & docker builder prune --force --filter until=168h --keep-storage 20GB
                if ($LASTEXITCODE -ne 0) { Write-Warning 'Build cache cleanup failed' }
            } else { Write-Warning 'Bounded build cache cleanup is unsupported; skipping' }
        }
    } catch { Write-Warning "Storage cleanup failed: $_" }
}
