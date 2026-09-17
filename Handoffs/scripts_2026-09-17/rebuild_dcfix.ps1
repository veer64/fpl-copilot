param([string]$Season)
$env:PYTHONUTF8 = "1"; $env:PYTHONUNBUFFERED = "1"
$tag = $Season.Replace("-", "_")
$repo = "C:\dev\fpl-copilot"
$log = "C:\Users\veers\AppData\Local\Temp\claude\c--dev-fpl-copilot\574ea3ed-213b-423b-b29f-4574a15eca54\scratchpad\rebuild_$tag.log"
Set-Location $repo
function Step($name, $cmdline) {
  "=== $name START $(Get-Date -Format o)" | Out-File -Append -Encoding utf8 $log
  cmd /c "uv run python $cmdline >> `"$log`" 2>&1"
  $code = $LASTEXITCODE
  "=== $name EXIT $code $(Get-Date -Format o)" | Out-File -Append -Encoding utf8 $log
  if ($code -ne 0) { "ABORT after $name" | Out-File -Append -Encoding utf8 $log; exit 1 }
}
"REBUILD $Season (DC boundary fix) started $(Get-Date -Format o)" | Out-File -Append -Encoding utf8 $log
Remove-Item "data\walkforward_h6_$tag.parquet" -ErrorAction SilentlyContinue
Step "canonical" "eval/walkforward_season.py --season $Season --horizon 6"
if ($Season -eq "2023-24") {
  Remove-Item "data\arms_gap0\walkforward_h6_${tag}_hmin.parquet" -ErrorAction SilentlyContinue
  Step "arms" "eval/walkforward_arms.py --season $Season --arms hmin --out-dir data/arms_gap0"
  Remove-Item "data\arms\armlog_${tag}_gap0_tc2.parquet","data\arms\armlog_${tag}_hmin_gap0.parquet" -ErrorAction SilentlyContinue
  Step "armlog_gap0_tc2" "eval/run_arms_full_system.py --season $Season --arm gap0 --tc2 25"
  Step "armlog_hmin_gap0" "eval/run_arms_full_system.py --season $Season --arm hmin_gap0"
}
if ($Season -eq "2024-25") {
  foreach ($a in @("props","hmin","both")) { Remove-Item "data\arms_gap0\walkforward_h6_${tag}_$a.parquet" -ErrorAction SilentlyContinue }
  Step "arms" "eval/walkforward_arms.py --season $Season --from-cutoff 8 --arms props,hmin,both --out-dir data/arms_gap0"
  Remove-Item "data\arms\armlog_${tag}_gap0_tc2.parquet","data\arms\armlog_${tag}_hmin_gap0.parquet","data\arms\armlog_${tag}_both_gap0.parquet" -ErrorAction SilentlyContinue
  Step "armlog_gap0_tc2" "eval/run_arms_full_system.py --season $Season --arm gap0 --tc2 24"
  Step "armlog_hmin_gap0" "eval/run_arms_full_system.py --season $Season --arm hmin_gap0"
  Step "armlog_both_gap0" "eval/run_arms_full_system.py --season $Season --arm both_gap0"
}
if ($Season -eq "2025-26") {
  foreach ($a in @("props","hmin","both")) { Remove-Item "data\arms_gap0\walkforward_h6_${tag}_$a.parquet" -ErrorAction SilentlyContinue }
  Step "arms" "eval/walkforward_arms.py --season $Season --arms props,hmin,both --out-dir data/arms_gap0"
  Remove-Item "data\arms\armlog_${tag}_gap0_tc2.parquet","data\arms\armlog_${tag}_hmin_gap0_tc2.parquet","data\arms\armlog_${tag}_both_gap0_tc2.parquet" -ErrorAction SilentlyContinue
  Step "armlog_gap0_tc2" "eval/run_arms_full_system.py --season $Season --arm gap0 --tc2 26"
  Step "armlog_hmin_gap0_tc2" "eval/run_arms_full_system.py --season $Season --arm hmin_gap0 --tc2 26"
  Step "armlog_both_gap0_tc2" "eval/run_arms_full_system.py --season $Season --arm both_gap0 --tc2 26"
}
"REBUILD $Season DONE $(Get-Date -Format o)" | Out-File -Append -Encoding utf8 $log
