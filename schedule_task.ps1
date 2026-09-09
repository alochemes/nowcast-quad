# Registers a Windows Task Scheduler job that runs the nowcast weekly
# (Monday 11:00 ET — machine typically not on earlier; a missed start runs
# at next boot, and NowcastQuadCatchUp covers longer gaps).
# Run once:  powershell -ExecutionPolicy Bypass -File schedule_task.ps1
# Remove:    Unregister-ScheduledTask -TaskName NowcastQuad -Confirm:$false

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "run_nowcast.py"

# --skip-if-fresh: if a run already succeeded in the last 20h (e.g. the logon
# catch-up task beat the weekly trigger), exit without running or emailing.
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`" --skip-if-fresh 20" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 11:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName "NowcastQuad" -Action $action -Trigger $trigger `
    -Settings $settings -Description "US growth/inflation quad nowcast (nowcast_quad)" -Force

Write-Output "Registered task 'NowcastQuad' (Mondays 11:00). Output: $root\output"
