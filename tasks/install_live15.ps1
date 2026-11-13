# Tradebot: registers the 15-minute PAPER bets job (research/PLAN15F.md). Run by tasks\install_live15.cmd.
# One task, \Tradebot\15-minute paper bets, for the signed-in user: no password stored, no administrator rights, no
# Windows setting changed. It runs pythonw.exe (no window) with research\live15.py tick, every 15 minutes from the next
# :01, :16, :31 or :46, only while you are signed in; starts and keeps running on battery; at most one copy at a time
# (a new start is skipped while one runs); stopped after 14 minutes; never wakes the PC; a run missed while the PC was
# off or asleep is not made up (a past window cannot be bet on). Everything is read back before it says OK.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $env:USERPROFILE 'Python313\pythonw.exe'
$script = Join-Path $root 'research\live15.py'
$name = '15-minute paper bets'
try {
    if (-not (Test-Path $py)) { throw "$py not found" }
    if (-not (Test-Path $script)) { throw "$script not found" }
    $now = Get-Date
    $at = $now.Date.AddHours($now.Hour).AddMinutes([math]::Floor($now.Minute / 15) * 15 + 1)
    if ($at -le $now) { $at = $at.AddMinutes(15) }
    $action = New-ScheduledTaskAction -Execute $py -Argument 'research\live15.py tick' -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Once -At $at -RepetitionInterval (New-TimeSpan -Minutes 15)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 14) -MultipleInstances IgnoreNew
    $settings.StartWhenAvailable = $false
    $settings.WakeToRun = $false
    Register-ScheduledTask -TaskPath '\Tradebot\' -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
        -Description 'Tradebot PLAN15F: 15-minute paper bets (research only; places no orders).' -Force | Out-Null
    $t = Get-ScheduledTask -TaskPath '\Tradebot\' -TaskName $name
    $s = $t.Settings
    if ($s.DisallowStartIfOnBatteries -or $s.StopIfGoingOnBatteries -or $s.WakeToRun -or $s.StartWhenAvailable) { throw 'the battery, wake or make-up settings did not read back as set' }
    $rep = $t.Triggers[0].Repetition
    if ([string]$rep.Interval -ne 'PT15M') { throw ('the repeat read back as {0}, not every 15 minutes' -f $rep.Interval) }
    $dur = [string]$rep.Duration
    if ($dur -ne '' -and $dur -notmatch '^P\d{4,}D$') {
        # some Windows versions store a one-day repeat when none is given: ask for the longest one Task Scheduler takes
        $t.Triggers[0].Repetition.Duration = 'P9999D'
        Set-ScheduledTask -TaskPath '\Tradebot\' -TaskName $name -Trigger $t.Triggers | Out-Null
        $dur = [string](Get-ScheduledTask -TaskPath '\Tradebot\' -TaskName $name).Triggers[0].Repetition.Duration
        if ($dur -ne '' -and $dur -notmatch '^P\d{4,}D$') { throw ('the repeat would stop after {0}' -f $dur) }
    }
    $i = Get-ScheduledTaskInfo -TaskPath '\Tradebot\' -TaskName $name
    Write-Output ('OK      {0}: every 15 minutes with no window, while you are signed in, on battery too, never wakes the PC; enabled: {1}; next run {2}' -f $name, $s.Enabled, $i.NextRunTime)
    exit 0
} catch {
    Write-Output ('FAILED  {0}: {1}' -f $name, $_.Exception.Message)
    exit 1
}
