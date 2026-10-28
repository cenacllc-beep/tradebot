# PLAN4 fetch chains, run detached so they survive this window closing (research only; places no orders).
#   powershell -NoProfile -ExecutionPolicy Bypass -File research\plan4_run.ps1 P   (Polymarket: pool, positions, selection, copies)
#   powershell -NoProfile -ExecutionPolicy Bypass -File research\plan4_run.ps1 K   (Kalshi: series, trade lists)
# Each step's output goes to research\results\plan4_log_<step>_<n>.txt; research\results\plan4_status_<chain>.txt shows
# progress. Scoring (scoreP, scoreK) is never run from here: each test is scored once, by hand, after the data checks.
param([string]$chain)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $env:USERPROFILE "Python313\python.exe"
$env:PYTHONIOENCODING = "utf-8"
if ($chain -eq "P") { $steps = @("ppool","ppositions","ppositions","ppositions","pselect","pcopies","pcopies") }
elseif ($chain -eq "K") { $steps = @("kseries","ktrades","ktrades") }
else { Write-Output "usage: plan4_run.ps1 P|K"; exit 1 }
$status = "research\results\plan4_status_$chain.txt"
$n = 0
foreach ($s in $steps) {
    $n += 1
    $out = "research\results\plan4_log_${s}_$n.txt"; $err = "research\results\plan4_log_${s}_${n}_err.txt"
    Add-Content $status ("{0} start {1}" -f (Get-Date -Format s), $s)
    $p = Start-Process -FilePath $py -ArgumentList @("-u","research\plan4.py",$s) -NoNewWindow -Wait -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    Add-Content $status ("{0} end {1} exit {2}" -f (Get-Date -Format s), $s, $p.ExitCode)
    if ($p.ExitCode -ne 0 -and $s -ne "pselect") { Add-Content $status "stopped"; exit $p.ExitCode }
    if ($p.ExitCode -ne 0) { Add-Content $status "stopped at pselect (see its log)"; exit $p.ExitCode }
}
Add-Content $status ("{0} done" -f (Get-Date -Format s))
