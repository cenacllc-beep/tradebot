# PLAN4 fetch chains, run detached so they survive this window closing (research only; places no orders).
#   powershell -NoProfile -ExecutionPolicy Bypass -File research\plan4_run.ps1 P   (Polymarket: pool, positions, selection, copies)
#   powershell -NoProfile -ExecutionPolicy Bypass -File research\plan4_run.ps1 K   (Kalshi: series, trade lists)
# Finishing chains (2026-10-29; the fetches above stopped on Oct 15 at pselect's format check, which has since been fixed):
#   KS   scoreK, then kquotes (K1 scored once; the descriptive quote check after it)
#   PS   pselect, pcopies (twice: the second run retries what failed), scoreP (P1, P2 and P2c scored once)
# Start both detached, so they survive the window closing (the laptop must stay awake and online for a few hours):
#   foreach ($c in "KS","PS") { Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","research\plan4_run.ps1",$c }
# Each step's output goes to research\results\plan4_log_<step>_<n>.txt; research\results\plan4_status_<chain>.txt shows
# progress. The scorers run in these chains only after every earlier step succeeded, and each refuses (nothing saved) on
# any of PLAN4's data guards, so each test is still scored once and only on complete data.
param([string]$chain)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $env:USERPROFILE "Python313\python.exe"
$env:PYTHONIOENCODING = "utf-8"
if ($chain -eq "P") { $steps = @("ppool","ppositions","ppositions","ppositions","pselect","pcopies","pcopies") }
elseif ($chain -eq "K") { $steps = @("kseries","ktrades","ktrades") }
elseif ($chain -eq "KS") { $steps = @("scoreK","kquotes") }
elseif ($chain -eq "PS") { $steps = @("pselect","pcopies","pcopies","scoreP") }
else { Write-Output "usage: plan4_run.ps1 P|K|KS|PS"; exit 1 }
$status = "research\results\plan4_status_$chain.txt"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
# a step whose single result already exists is skipped, so a finishing chain can be started again after a failure
$doneIf = @{ "pselect" = "research\results\plan4_selected.json"; "scoreP" = "research\results\plan4_P.json"; "scoreK" = "research\results\plan4_K.json" }
$n = 0
foreach ($s in $steps) {
    $n += 1
    if ($chain -in @("KS","PS") -and $doneIf.ContainsKey($s) -and (Test-Path $doneIf[$s])) { Add-Content $status ("{0} skip {1} (its result exists)" -f (Get-Date -Format s), $s); continue }
    $out = "research\results\plan4_log_${s}_$n.txt"; $err = "research\results\plan4_log_${s}_${n}_err.txt"
    if ($chain -in @("KS","PS")) { $out = "research\results\plan4_log_${chain}_${stamp}_${s}_$n.txt"; $err = "research\results\plan4_log_${chain}_${stamp}_${s}_${n}_err.txt" }
    Add-Content $status ("{0} start {1}" -f (Get-Date -Format s), $s)
    $p = Start-Process -FilePath $py -ArgumentList @("-u","research\plan4.py",$s) -NoNewWindow -Wait -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    Add-Content $status ("{0} end {1} exit {2}" -f (Get-Date -Format s), $s, $p.ExitCode)
    if ($p.ExitCode -ne 0 -and $s -ne "pselect") { Add-Content $status "stopped"; exit $p.ExitCode }
    if ($p.ExitCode -ne 0) { Add-Content $status "stopped at pselect (see its log)"; exit $p.ExitCode }
}
Add-Content $status ("{0} done" -f (Get-Date -Format s))
