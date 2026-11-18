try {
    . (Join-Path $PSScriptRoot 'Common.ps1')
    Require-Python; Check-Integrity; Ensure-Docker; Ensure-Services
    & $pythonExe -B (Join-Path $teamRoot 'research\run.py') wizard
    exit $LASTEXITCODE
} catch { Write-Host ('STOPPED: '+$_.Exception.Message) -ForegroundColor Red; exit 1 }
