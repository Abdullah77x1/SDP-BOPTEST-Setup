$ErrorActionPreference = 'Stop'
$teamRoot = $PSScriptRoot
$releaseRoot = Join-Path $teamRoot 'runtime\project1-boptest-0.9.0'
$pythonExe = Join-Path $teamRoot '.venv\Scripts\python.exe'
$projectName = 'boptest-team-v090'
$apiUrl = 'http://127.0.0.1:80'
function Find-Docker {
    $command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @((Join-Path $env:USERPROFILE 'AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'),(Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'))) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw 'Docker Desktop is missing. Install it with WSL2 / Linux containers, then retry.'
}
function Invoke-Docker([string[]]$Arguments) {
    & $dockerExe @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw ('Docker failed: ' + ($Arguments -join ' ')) }
}
function Compose-Args {
    return @('compose','--project-directory',$releaseRoot,'--env-file',(Join-Path $releaseRoot '.env'),'-p',$projectName,'-f',(Join-Path $releaseRoot 'docker-compose.yml'),'-f',(Join-Path $teamRoot 'compose.team.yml'))
}
function Invoke-Compose([string[]]$Arguments) { Invoke-Docker -Arguments ((Compose-Args) + $Arguments) }
function Ensure-Docker {
    $script:dockerExe = Find-Docker
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $mode = & $dockerExe info --format '{{.OSType}}' 2>$null
    $engineExit = $LASTEXITCODE
    $ErrorActionPreference = $oldPreference
    if ($engineExit -ne 0) {
        $desktop = Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $dockerExe))) 'Docker Desktop.exe'
        if (Test-Path -LiteralPath $desktop) { Start-Process -FilePath $desktop -WindowStyle Hidden }
        Write-Host 'Waiting for Docker Desktop (up to 3 minutes). Enable WSL2 and finish its first-run prompts if shown.'
        $deadline = (Get-Date).AddMinutes(3)
        do {
            Start-Sleep -Seconds 3
            $ErrorActionPreference = 'Continue'
            $mode = & $dockerExe info --format '{{.OSType}}' 2>$null
            $engineExit = $LASTEXITCODE
            $ErrorActionPreference = $oldPreference
            if ($engineExit -eq 0) { break }
        } while ((Get-Date) -lt $deadline)
        if ($engineExit -ne 0) { throw 'Docker Engine is unavailable. Open Docker Desktop, check WSL2/virtualization, and retry. Nothing was simulated.' }
    }
    if ($mode -ne 'linux') { throw 'Switch Docker Desktop to Linux containers.' }
    $arch = & $dockerExe info --format '{{.Architecture}}'
    if ($LASTEXITCODE -ne 0 -or $arch -notin @('x86_64','amd64')) { throw 'Linux AMD64 is required; use an Intel/AMD Windows computer.' }
    $version = & $dockerExe compose version --short
    if ($LASTEXITCODE -ne 0 -or [version](($version -replace '^v','') -replace '-.*$','') -lt [version]'2.24.4') { throw 'Update Docker Desktop; Compose 2.24.4 or newer is required.' }
    $env:PATH = (Split-Path -Parent $dockerExe) + ';' + $env:PATH
}
function Require-Python {
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run SETUP_FIRST.cmd to create the Python environment.' }
    & $pythonExe -B -c "import sys,ssl,csv,json,urllib.request; assert sys.version_info[:2] == (3,12), 'Python 3.12 required'"
    if ($LASTEXITCODE -ne 0) { throw 'The virtual environment is invalid or was moved. Rename .venv to .venv-old and rerun SETUP_FIRST.cmd.' }
}
function Check-Integrity {
    & $pythonExe -B (Join-Path $teamRoot 'tools\integrity.py')
    if ($LASTEXITCODE -ne 0) { throw 'Package integrity failed. Extract an unchanged distribution ZIP into a new folder.' }
}
function Read-Api([string]$Url) {
    $data = Invoke-RestMethod -Uri $Url -TimeoutSec 5
    if ($data.PSObject.Properties['status']) {
        if ($data.status -ne 200) { throw ('API failure: ' + $data.message) }
        return $data.payload
    }
    return $data
}
function Read-Catalog {
    try { return Read-Api ($apiUrl+'/testcases') }
    catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) { return @() }
        throw
    }
}
function Service-Id([string]$Name) {
    $ids = & $dockerExe @(Compose-Args) ps -a -q $Name
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect this package Docker project.' }
    return $ids
}
function Wait-Service([string]$Name) {
    $deadline = (Get-Date).AddMinutes(5)
    do {
        $id = Service-Id $Name
        if ($id) {
            $raw = & $dockerExe inspect --format '{{json .State}}' $id
            if ($LASTEXITCODE -ne 0) { throw ('Cannot inspect ' + $Name) }
            $state = $raw | ConvertFrom-Json
            if ($state.Status -eq 'exited') {
                if ($state.ExitCode -ne 0) { throw ($Name + ' failed. Inspect logs using GUIDE.md.') }
                return
            }
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw ($Name + ' timed out. No building was initialized.')
}
function Check-Bindings {
    foreach ($pair in @(@('web','80'),@('minio','9000'),@('minio','9001'))) {
        $binding = & $dockerExe @(Compose-Args) port $pair[0] $pair[1]
        if ($LASTEXITCODE -ne 0 -or $binding -ne ('127.0.0.1:'+$pair[1])) { throw ('Unexpected public/missing binding for ' + $pair[0]) }
    }
}
function Ensure-Services {
    if (-not (Test-Path -LiteralPath (Join-Path $releaseRoot 'docker-compose.yml'))) { throw 'Run SETUP_FIRST.cmd before opening BOPTEST.' }
    foreach ($pair in @(@('web',80),@('minio',9000),@('minio',9001))) {
        $listeners = Get-NetTCPConnection -LocalPort $pair[1] -State Listen -ErrorAction SilentlyContinue
        if ($listeners) {
            $id = Service-Id $pair[0]
            $running = if ($id) { & $dockerExe inspect --format '{{.State.Running}}' $id } else { 'false' }
            if ($running -ne 'true') { throw ('Port '+$pair[1]+' is occupied by another application or BOPTEST project. Stop that application first; it was left unchanged.') }
        }
    }
    foreach ($name in @('minio','redis')) {
        $id = Service-Id $name
        if (-not $id) { Invoke-Compose -Arguments @('up','-d','--no-build','--pull','never','--no-deps',$name) }
        else { Invoke-Docker -Arguments @('start',$id) }
    }
    $ready = $false; $deadline = (Get-Date).AddSeconds(90)
    do {
        try { $ready = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9000/minio/health/ready' -TimeoutSec 3).StatusCode -eq 200 } catch {}
        if ($ready) { break }; Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    if (-not $ready) { throw 'Storage did not become ready. No building was initialized.' }
    $webId = Service-Id 'web'
    $webRunning = if ($webId) { & $dockerExe inspect --format '{{.State.Running}}' $webId } else { 'false' }
    if ($webRunning -ne 'true') {
        Invoke-Compose -Arguments @('up','-d','--no-build','--pull','never','--no-deps','mc')
        $mcId = Service-Id 'mc'
        $mcStatus = & $dockerExe inspect --format '{{.State.Status}}' $mcId
        if ($mcStatus -eq 'exited') {
            $mcExit = & $dockerExe inspect --format '{{.State.ExitCode}}' $mcId
            if ($mcExit -ne '0') { throw 'Storage bootstrap failed. Inspect mc logs; no automatic replacement/retry.' }
        }
        Wait-Service 'mc'
    }
    foreach ($name in @('worker','web')) {
        $id = Service-Id $name
        if (-not $id) { Invoke-Compose -Arguments @('up','-d','--no-build','--pull','never','--no-deps',$name) }
        else { Invoke-Docker -Arguments @('start',$id) }
    }
    $deadline = (Get-Date).AddSeconds(90); $version = $null
    do {
        try { $version = Read-Api ($apiUrl+'/version') } catch {}
        if ($version) { break }; Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    if (-not $version -or $version.version -ne '0.9.0') { throw 'BOPTEST API is unavailable or is not version 0.9.0.' }
    Check-Bindings
    $catalog = Read-Catalog
    if (-not (($catalog | ConvertTo-Json -Depth 10 -Compress) -match '"bestest_air"')) {
        Invoke-Compose -Arguments @('up','-d','--no-build','--pull','never','--no-deps','provision')
        $id = Service-Id 'provision'
        $state = & $dockerExe inspect --format '{{.State.Status}}' $id
        if ($state -eq 'exited') {
            $provisionExit = & $dockerExe inspect --format '{{.State.ExitCode}}' $id
            if ($provisionExit -ne '0') { throw 'Building provisioning failed. Inspect provision logs.' }
        }
        Wait-Service 'provision'
        $catalog = Read-Catalog
        if (-not (($catalog | ConvertTo-Json -Depth 10 -Compress) -match '"bestest_air"')) { throw 'Building provisioning failed: bestest_air is absent.' }
    }
}
