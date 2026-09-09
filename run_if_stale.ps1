# Catch-up runner: if the weekly nowcast for the current cycle hasn't succeeded
# yet, run it now. Registered at user logon (NowcastQuadCatchUp) so a machine
# that was off at the scheduled time refreshes itself minutes after coming back.
#
# It is anchored to the schedule, not to an age threshold. An age gate cannot be
# tuned correctly and has now failed in both directions:
#   - 6 days  ran on a Monday logon before the weekly task fired -> two emails
#             (observed 2026-07-27)
#   - 8 days  can never cover a missed weekly run, because a same-day logon sees
#             a run only ~7.1 days old and declines. On 2026-09-07 the PC was off
#             at 11:00, booted 13:46, this script ran 14:14, measured 7.13 days
#             <= 8, skipped -- and the nowcast went 9 days stale.
# "Has a run succeeded since the most recent scheduled Monday 11:00?" has neither
# failure mode, no parameter to tune, and no week-over-week drift.
#
# Keep DueDayOfWeek/DueHour in sync with the trigger in schedule_task.ps1.
param(
    [System.DayOfWeek]$DueDayOfWeek = [System.DayOfWeek]::Monday,
    [int]$DueHour = 11
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $root "output\run.log"

function Get-LastLogTime([string[]]$lines, [string]$pattern) {
    $hit = $lines | Select-String $pattern | Select-Object -Last 1
    if ($hit -and $hit.Line -match "^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]") {
        return [datetime]::ParseExact($Matches[1], "yyyy-MM-dd HH:mm:ss", $null)
    }
    return $null
}

$now = Get-Date
$lines = if (Test-Path $log) { Get-Content $log -Tail 400 } else { @() }
$okTime = Get-LastLogTime $lines "run OK"
$startTime = Get-LastLogTime $lines "nowcast run start"

# Most recent scheduled slot at or before now.
$due = (Get-Date -Hour $DueHour -Minute 0 -Second 0).Date.AddHours($DueHour)
while ($due.DayOfWeek -ne $DueDayOfWeek -or $due -gt $now) { $due = $due.AddDays(-1) }

if ($okTime -and $okTime -ge $due) {
    Write-Output ("up to date (last OK " + $okTime.ToString("yyyy-MM-dd HH:mm") +
                  " >= due " + $due.ToString("yyyy-MM-dd HH:mm") + "), skipping")
    exit 0
}

# The weekly task may have started seconds ago and not yet logged "run OK";
# starting a second, concurrent run here would double the work and the email.
if ($startTime -and ($now - $startTime).TotalMinutes -lt 30) {
    Write-Output ("a run started " + $startTime.ToString("yyyy-MM-dd HH:mm") +
                  " and may still be in flight, skipping")
    exit 0
}

Write-Output ("due " + $due.ToString("yyyy-MM-dd HH:mm") + " not yet satisfied - running nowcast now")
& (Join-Path $root ".venv\Scripts\python.exe") (Join-Path $root "run_nowcast.py") --skip-if-fresh 20
exit $LASTEXITCODE
