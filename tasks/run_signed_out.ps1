# Tradebot: lets the three scheduled jobs run whether or not you are signed in (added 2026-10-29 at the user's request,
# after Windows Update restarted the PC at 4:59 AM and no job ran until someone signed in at 1:28 PM).
#
# It changes only the three Tradebot tasks, and only how they sign in:
#   - the same Windows account, now "Run whether user is logged on or not" with "Do not store password" (Task
#     Scheduler's S4U logon);
#   - no password is asked for or stored;
#   - the run level stays Limited, so the jobs get no administrator rights;
#   - what each task runs (actions), when (triggers) and its other settings (battery, missed runs, wake, time limit,
#     enabled) stay as they are, and all of them are read back.
# With S4U the jobs run in the background with no window, also at the sign-in screen after a restart. They reach the
# internet as before, but not shared network folders, which the bot does not use.
# Windows needs administrator permission for this change, so start it with run_signed_out.cmd, which asks.
# install_schedules.cmd re-creates the tasks as "only while signed in", so run this again after it.
# Undo: run_signed_out.cmd undo (or Task Scheduler, Tradebot, each task, General, "Run only when user is logged on").
# Writes logs\signed_out.txt. Exit code: 0 when all three tasks read back as wanted, otherwise the number that failed.
param([switch]$Undo)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root 'logs\signed_out.txt'
$folder = '\Tradebot\'
$names = @('Evening scan', 'Afternoon settle', 'Hourly research')
$want = if ($Undo) { 'Interactive' } else { 'S4U' }
$out = New-Object System.Collections.Generic.List[string]
$out.Add(('{0} {1}' -f (Get-Date -Format s), $(if ($Undo) { 'switching the Tradebot jobs back to: only while signed in' } else { 'switching the Tradebot jobs to: whether or not signed in' })))
$failed = 0
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    $failed = $names.Count
    $out.Add('FAILED  not running with administrator permission: start tasks\run_signed_out.cmd and answer Yes')
} else {
    foreach ($n in $names) {
        try {
            $t = Get-ScheduledTask -TaskPath $folder -TaskName $n   # stops here if the task does not exist
            $s0 = $t.Settings
            $before = @($s0.DisallowStartIfOnBatteries, $s0.StopIfGoingOnBatteries, $s0.StartWhenAvailable, $s0.WakeToRun, $s0.ExecutionTimeLimit, $s0.Enabled,
                        (($t.Actions | ForEach-Object { '{0} {1}' -f $_.Execute, $_.Arguments }) -join ';'),
                        (($t.Triggers | ForEach-Object { '{0} {1}' -f $_.StartBoundary, $_.Repetition.Interval }) -join ';'))
            $p = New-ScheduledTaskPrincipal -UserId $t.Principal.UserId -LogonType $want -RunLevel Limited
            Set-ScheduledTask -TaskPath $folder -TaskName $n -Principal $p | Out-Null
            $r = Get-ScheduledTask -TaskPath $folder -TaskName $n
            $s1 = $r.Settings
            $after = @($s1.DisallowStartIfOnBatteries, $s1.StopIfGoingOnBatteries, $s1.StartWhenAvailable, $s1.WakeToRun, $s1.ExecutionTimeLimit, $s1.Enabled,
                       (($r.Actions | ForEach-Object { '{0} {1}' -f $_.Execute, $_.Arguments }) -join ';'),
                       (($r.Triggers | ForEach-Object { '{0} {1}' -f $_.StartBoundary, $_.Repetition.Interval }) -join ';'))
            if ([string]$r.Principal.LogonType -ne $want -or [string]$r.Principal.RunLevel -ne 'Limited') {
                throw ('read back as {0}, {1}' -f $r.Principal.LogonType, $r.Principal.RunLevel)
            }
            if (($before -join '|') -ne ($after -join '|')) { throw ('other settings changed: {0} -> {1}' -f ($before -join '|'), ($after -join '|')) }
            $how = if ($Undo) { 'runs only while you are signed in' } else { 'runs whether or not you are signed in (no password stored)' }
            $next = 'unknown'
            try { $next = (Get-ScheduledTaskInfo -TaskPath $folder -TaskName $n).NextRunTime } catch { }
            $out.Add(('OK      {0}: {1}; next run {2}' -f $n, $how, $next))
        } catch {
            $failed++
            $out.Add(('FAILED  {0}: {1}' -f $n, $_.Exception.Message))
        }
    }
}
try {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null
    Set-Content -Path $log -Value $out -Encoding Oem   # no byte-order mark, so `type` shows it cleanly
} catch { $out.Add(('could not write {0}: {1}' -f $log, $_.Exception.Message)) }
$out | ForEach-Object { Write-Output $_ }
exit $failed
