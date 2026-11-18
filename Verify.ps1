param([switch]$Offline)
try {
    . (Join-Path $PSScriptRoot 'Common.ps1')
    Require-Python; Check-Integrity
    if ($Offline) { & $pythonExe -B (Join-Path $teamRoot 'tools\verify.py') --offline }
    else { Ensure-Docker; Ensure-Services; & $pythonExe -B (Join-Path $teamRoot 'tools\verify.py') }
    exit $LASTEXITCODE
} catch {
    $failure = $_.Exception.Message
    $reportRoot = Join-Path $PSScriptRoot ('verification\prerequisite_'+(Get-Date -Format 'yyyyMMdd_HHmmss_fff')+'_'+[guid]::NewGuid().ToString('N').Substring(0,8))
    New-Item -ItemType Directory -Path $reportRoot -Force | Out-Null
    @{status='FAIL';stage='PREREQUISITES_OR_SERVICE_STARTUP';error=$failure;live_simulation='NOT_RUN'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportRoot 'REPORT.json') -Encoding UTF8
    Write-Host ('FAIL: '+$failure) -ForegroundColor Red
    Write-Host ('Report: '+$reportRoot)
    exit 1
}
