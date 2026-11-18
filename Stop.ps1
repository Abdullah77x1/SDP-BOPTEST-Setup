try {
    . (Join-Path $PSScriptRoot 'Common.ps1')
    Require-Python
    $dockerExe = Find-Docker
    $env:PATH = (Split-Path -Parent $dockerExe) + ';' + $env:PATH
    & $pythonExe -B (Join-Path $teamRoot 'tools\stop.py')
    if ($LASTEXITCODE -ne 0) { throw 'Stop was blocked by a running/unknown building session or a Docker error; inspect the message above.' }
    Write-Host 'BOPTEST services stopped. Generated datasets remain on disk.'
    exit 0
} catch { Write-Host ('STOPPED: '+$_.Exception.Message) -ForegroundColor Red; exit 1 }
