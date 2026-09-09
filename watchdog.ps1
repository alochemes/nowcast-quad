# NowcastQuad watchdog: silent when healthy, toast alert when the weekly run
# is stale (> 8 days) or the last run failed. Registered as a daily task.
# Usage: powershell -ExecutionPolicy Bypass -File watchdog.ps1 [-Verbose] [-TestAlert]
param([switch]$TestAlert, [switch]$VerboseCheck)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $root "output\run.log"
$notify = Join-Path $root "notify.ps1"

function Alert($body) {
    powershell -ExecutionPolicy Bypass -File $notify -Title "Nowcast Quad: ATTENTION" -Body $body
}

if ($TestAlert) { Alert "Test alert - the watchdog notification path works."; exit 0 }

if (-not (Test-Path $log)) { Alert "run.log missing - no runs recorded."; exit 1 }

$lines = Get-Content $log -Tail 400
$lastOk = ($lines | Select-String "run OK" | Select-Object -Last 1)
$lastFail = ($lines | Select-String "run FAILED" | Select-Object -Last 1)

$okTime = $null
if ($lastOk -and $lastOk.Line -match "^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]") {
    $okTime = [datetime]::ParseExact($Matches[1], "yyyy-MM-dd HH:mm:ss", $null)
}
$failTime = $null
if ($lastFail -and $lastFail.Line -match "^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]") {
    $failTime = [datetime]::ParseExact($Matches[1], "yyyy-MM-dd HH:mm:ss", $null)
}

$problems = @()
if (-not $okTime) {
    $problems += "no successful run found in run.log"
} elseif ((Get-Date) - $okTime -gt [TimeSpan]::FromDays(8)) {
    $problems += "last successful run was $($okTime.ToString('yyyy-MM-dd HH:mm')) (>8 days ago)"
}
if ($failTime -and $okTime -and $failTime -gt $okTime) {
    $problems += "most recent run FAILED at $($failTime.ToString('yyyy-MM-dd HH:mm')) - see output\run.log"
}

$task = Get-ScheduledTask -TaskName "NowcastQuad" -ErrorAction SilentlyContinue
if (-not $task) { $problems += "scheduled task 'NowcastQuad' is not registered" }

if ($problems.Count -gt 0) {
    Alert ($problems -join "; ")
    Write-Output ("ALERT: " + ($problems -join "; "))
    exit 1
}
if ($VerboseCheck) {
    Write-Output ("healthy - last OK run " + $okTime.ToString("yyyy-MM-dd HH:mm"))
}
exit 0
