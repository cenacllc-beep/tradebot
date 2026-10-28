# Tradebot: finishes the three schedules that install_schedules.cmd creates (added 2026-10-23, outage review).
#
# schtasks.exe can create a schedule but cannot set its power or catch-up options, so Windows uses its defaults
# (Task Scheduler schema, settingsType): DisallowStartIfOnBatteries=true, StopIfGoingOnBatteries=true,
# StartWhenAvailable=false. On this laptop that means: no run at all while it is unplugged, a run killed when the
# charger is pulled out, and a run missed while the PC was off or asleep is skipped, never made up.
#
# This script changes only these three Tradebot tasks, and only these settings:
#   - start, and keep running, on battery;
#   - start a missed run as soon as the PC is available (evening.cmd then scans only from 8:50 PM to 1 AM: scan_window.py);
#   - a time limit per run (at most one copy of each job runs at a time: Windows' default, kept);
#   - since 2026-10-25, the 8:55 PM Evening scan only: wake the PC from sleep to run (on Oct 24 the laptop slept from
#     11:39 AM to 11:53 PM, and the scan ran only because it happened to wake before 1 AM). The job keeps the PC awake
#     only while a step runs, so it goes back to sleep afterwards. To stop it: Task Scheduler, Tradebot, Evening scan,
#     Conditions, clear "Wake the computer to run this task". The other two tasks never wake the PC.
# What each task runs, when, and whether it is enabled stay as they are (changed in place, review 2026-10-24). It stores
# no password, needs no administrator rights and changes no Windows setting: whether Windows honours wake timers is a
# power-plan setting ("Allow wake timers"), which this script only reads and reports. Runs happen only while you are
# signed in.
# Exit code: 0 when all three tasks were updated and read back correctly, otherwise the number that failed.
$ErrorActionPreference = 'Stop'
$folder = '\Tradebot\'
$jobs = @(
    @{ Name = 'Evening scan';     Hours = 6; Wake = $true },    # may wait for the network until 1 AM; jobs.py stops waiting at 5.5 h
    @{ Name = 'Afternoon settle'; Hours = 3; Wake = $false },   # an hour's network wait, then the lock; jobs.py stops at 2.5 h
    @{ Name = 'Hourly research';  Hours = 2; Wake = $false }
)
$failed = 0
foreach ($j in $jobs) {
    try {
        # The task's own settings, changed in place: whether you disabled it, and anything else you set, stays as it is.
        $t = Get-ScheduledTask -TaskPath $folder -TaskName $j.Name   # stops here if schtasks did not create it
        $t.Settings.DisallowStartIfOnBatteries = $false
        $t.Settings.StopIfGoingOnBatteries = $false
        $t.Settings.StartWhenAvailable = $true
        $t.Settings.ExecutionTimeLimit = 'PT{0}H' -f $j.Hours
        $t.Settings.WakeToRun = [bool]$j.Wake
        Set-ScheduledTask -InputObject $t | Out-Null
        $s = (Get-ScheduledTask -TaskPath $folder -TaskName $j.Name).Settings
        if ($s.DisallowStartIfOnBatteries -or $s.StopIfGoingOnBatteries -or -not $s.StartWhenAvailable -or [System.Xml.XmlConvert]::ToTimeSpan($s.ExecutionTimeLimit) -ne [TimeSpan]::FromHours($j.Hours) -or [bool]$s.WakeToRun -ne [bool]$j.Wake) {
            throw 'the new settings did not read back'
        }
        $next = (Get-ScheduledTaskInfo -TaskPath $folder -TaskName $j.Name).NextRunTime
        $wakes = if ($s.WakeToRun) { 'wakes the PC to run' } else { 'does not wake the PC' }
        Write-Output ('OK      {0}: runs on battery, makes up a missed run, {1}; enabled: {2}; next run {3}' -f $j.Name, $wakes, $s.Enabled, $next)
    } catch {
        $failed++
        Write-Output ('FAILED  {0}: {1}' -f $j.Name, $_.Exception.Message)
    }
}
# Read only: does the power plan let a scheduled task wake the PC? "Allow wake timers" (GUID below): 0 off, 1 on,
# 2 important timers only (Task Scheduler's are not "important", so 2 means no wake). Found by its GUID and the two
# 0x values after it (AC, then DC), so a Windows in another language reads the same. Never changes it, never fails.
$guid = 'bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d'
$names = @{ 0 = 'off'; 1 = 'on'; 2 = 'important timers only (so not this one)' }
$q = ''; $qerr = $null
try { $q = (powercfg /q SCHEME_CURRENT SUB_SLEEP $guid 2>&1) -join "`n" } catch { $q = ''; $qerr = $_.Exception.Message }
if ($q.IndexOf($guid, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
    try { $q = (powercfg /qh SCHEME_CURRENT SUB_SLEEP $guid 2>&1) -join "`n"; $qerr = $null } catch { $q = ''; if (-not $qerr) { $qerr = $_.Exception.Message } }   # hidden settings too
}
try {
    $i = $q.IndexOf($guid, [StringComparison]::OrdinalIgnoreCase)
    if ($i -lt 0 -and $qerr) {
        Write-Output ('INFO    power plan "Allow wake timers": could not be read ({0}), so the 8:55 PM scan may not wake the PC' -f $qerr)
    } elseif ($i -lt 0) {
        Write-Output 'INFO    power plan "Allow wake timers": not present on this PC, so the 8:55 PM scan may not wake it'
    } else {
        $m = [regex]::Matches($q.Substring($i), ':\s*0x([0-9a-fA-F]+)')
        if ($m.Count -lt 2) {
            Write-Output 'INFO    power plan "Allow wake timers": present, but its values could not be read'
        } else {
            $a = [Convert]::ToInt32($m[$m.Count - 2].Groups[1].Value, 16)
            $d = [Convert]::ToInt32($m[$m.Count - 1].Groups[1].Value, 16)
            $an = if ($names.ContainsKey($a)) { $names[$a] } else { 'value {0}' -f $a }
            $dn = if ($names.ContainsKey($d)) { $names[$d] } else { 'value {0}' -f $d }
            Write-Output ('INFO    power plan "Allow wake timers": plugged in {0}; on battery {1}' -f $an, $dn)
            if ($d -eq 1) {
                Write-Output 'INFO    on battery the 8:55 PM scan can wake the laptop with its lid closed, even in a bag (it runs a few minutes and may get warm). Shut it down or hibernate it before packing it, or set Allow wake timers "On battery" to Disable so it wakes only when plugged in.'
            }
            if ($a -ne 1 -and $d -ne 1) {
                Write-Output 'INFO    so Windows will not wake the PC for the 8:55 PM scan. To allow it while plugged in: Control Panel, Power Options, Change plan settings, Change advanced power settings, Sleep, Allow wake timers, Plugged in: Enable.'
            }
        }
    }
} catch {
    Write-Output ('INFO    power plan "Allow wake timers": could not be read ({0})' -f $_.Exception.Message)
}
# Read only: "Network connectivity in Standby" (GUID below). On a PC with Modern Standby, Disable means no network
# while the screen is off, even though scheduled jobs still run: on Oct 25 and 26 every hourly job ran on time and
# found no network for hours. Shown with this PC's own names for the values. Never changes it, never fails.
function Show-PowerSetting([string]$sub, [string]$alias, [string]$sguid, [string]$label) {
    try {
        $t = ''; $terr = $null   # $alias names the setting for people; the query uses its GUID, which always works
        try { $t = (powercfg /q SCHEME_CURRENT $sub $sguid 2>&1) -join "`n" } catch { $t = ''; $terr = $_.Exception.Message }
        if ($t.IndexOf($sguid, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            try { $t = (powercfg /qh SCHEME_CURRENT $sub $sguid 2>&1) -join "`n"; $terr = $null } catch { $t = ''; if (-not $terr) { $terr = $_.Exception.Message } }
        }
        $i = $t.IndexOf($sguid, [StringComparison]::OrdinalIgnoreCase)
        if ($i -lt 0 -and $terr) { Write-Output ('INFO    {0}: could not be read ({1})' -f $label, $terr); return }
        if ($i -lt 0) { Write-Output ('INFO    {0}: not present on this PC' -f $label); return }
        $lines = $t.Substring($i) -split "`n"
        $vn = @{}
        for ($k = 0; $k -lt $lines.Count - 1; $k++) {
            $mi = [regex]::Match($lines[$k], ':\s*([0-9]{3})\s*$')
            if ($mi.Success) { $vn[[Convert]::ToInt32($mi.Groups[1].Value, 10)] = ($lines[$k + 1] -split ':', 2)[-1].Trim() }
        }
        $m = [regex]::Matches($t.Substring($i), ':\s*0x([0-9a-fA-F]+)')
        if ($m.Count -lt 2) { Write-Output ('INFO    {0}: present, but its values could not be read' -f $label); return }
        $a = [Convert]::ToInt32($m[$m.Count - 2].Groups[1].Value, 16)
        $d = [Convert]::ToInt32($m[$m.Count - 1].Groups[1].Value, 16)
        $an = if ($vn.ContainsKey($a)) { $vn[$a] } else { 'value' }
        $dn = if ($vn.ContainsKey($d)) { $vn[$d] } else { 'value' }
        Write-Output ('INFO    {0}: plugged in {1} ({2}); on battery {3} ({4})' -f $label, $an, $a, $dn, $d)
    } catch {
        Write-Output ('INFO    {0}: could not be read ({1})' -f $label, $_.Exception.Message)
    }
}
Show-PowerSetting 'SUB_NONE' 'CONNECTIVITYINSTANDBY' 'f15576e8-98b7-4186-b944-eafa664402d9' 'power plan "Network connectivity in Standby"'
# Read only: which sleep states this PC has (Modern Standby keeps the network off in standby, and a timer wake may not
# turn it back on; the evening job then waits for the network until 1 AM).
try {
    $sa = (powercfg /a 2>&1) | ForEach-Object { ('{0}' -f $_).Trim() } | Where-Object { $_ }
    Write-Output ('INFO    sleep states (powercfg /a): {0}' -f ($sa -join ' | '))
} catch {
    Write-Output ('INFO    sleep states: could not be read ({0})' -f $_.Exception.Message)
}
exit $failed
