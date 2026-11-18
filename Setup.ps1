param([switch]$Rebuild)
try {
    . (Join-Path $PSScriptRoot 'Common.ps1')
    Set-Location -LiteralPath $teamRoot
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        if (Get-Command py -ErrorAction SilentlyContinue) { & py -3.12 -m venv (Join-Path $teamRoot '.venv') }
        else {
            & python -c "import sys; assert sys.version_info[:2] == (3,12), 'Install Python 3.12'"
            if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 from python.org with the Python launcher, then reopen setup.' }
            & python -m venv (Join-Path $teamRoot '.venv')
        }
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 environment creation failed. Install Python 3.12 with the Python launcher.' }
    }
    Require-Python; Check-Integrity; Ensure-Docker
    $runtime = Join-Path $teamRoot 'runtime'
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    $archive = Join-Path $runtime 'boptest-v0.9.0.zip'
    if (-not (Test-Path -LiteralPath $archive)) {
        Write-Host 'Downloading official BOPTEST v0.9.0 (310 MB)...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $download = $archive+'.download'
        Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/ibpsa/project1-boptest/releases/download/v0.9.0/project1-boptest-0.9.0.zip' -OutFile $download
        if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash -ne '173a3edb67d904e114e5e88ec3e6b4a6de3b325fe68676311d84e6d500a90608') { throw 'Downloaded archive checksum mismatch. The unverified download was not installed.' }
        Move-Item -LiteralPath $download -Destination $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne '173a3edb67d904e114e5e88ec3e6b4a6de3b325fe68676311d84e6d500a90608') { throw 'Checksum mismatch: rename runtime\boptest-v0.9.0.zip and rerun setup.' }
    & $pythonExe -B (Join-Path $teamRoot 'tools\release.py') $archive $runtime
    if ($LASTEXITCODE -ne 0) { throw 'Official release extraction/integrity failed. See the error above.' }
    Invoke-Compose -Arguments @('config','--quiet')
    $resolvedRaw = & $dockerExe @(Compose-Args) config --format json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve Compose configuration.' }
    $resolved = $resolvedRaw | ConvertFrom-Json
    foreach ($service in @('minio','mc','redis','web','worker','provision')) {
        $image = $resolved.services.$service.image
        if (-not $image) { $image = $projectName+'-'+$service }
        $exists = & $dockerExe image ls -q $image
        if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect cached images.' }
        if (-not $exists -or $Rebuild) {
            if ($service -in @('minio','mc','redis')) { Invoke-Compose -Arguments @('pull',$service) }
            else { Invoke-Compose -Arguments @('build',$service) }
        } else { Write-Host ('Reusing cached '+$service+' image.') }
    }
    Ensure-Services
    Write-Host 'Services ready. No building simulation has been tested yet.' -ForegroundColor Green
    Write-Host 'Run VERIFY_INSTALL.cmd for the independent three-step simulation test. Use GENERATE_DATASET.cmd to record a new experiment.'
    exit 0
} catch { Write-Host ('STOPPED: '+$_.Exception.Message) -ForegroundColor Red; exit 1 }
