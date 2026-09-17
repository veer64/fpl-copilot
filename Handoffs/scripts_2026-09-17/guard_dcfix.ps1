param([string]$Season, [string]$Config, [string]$Cutoffs, [string]$Tag)
$env:PYTHONUTF8 = "1"; $env:PYTHONUNBUFFERED = "1"
$repo = "C:\dev\fpl-copilot"
$log = "C:\Users\veers\AppData\Local\Temp\claude\c--dev-fpl-copilot\574ea3ed-213b-423b-b29f-4574a15eca54\scratchpad\guard_$Tag.log"
Set-Location $repo
"=== GUARD $Season $Config cutoffs [$Cutoffs] START $(Get-Date -Format o)" | Out-File -Append -Encoding utf8 $log
cmd /c "uv run python eval/asof_reconstruction.py --season $Season --cutoffs $($Cutoffs.Replace(",", " ")) --config $Config --reference record >> `"$log`" 2>&1"
"=== GUARD EXIT $LASTEXITCODE $(Get-Date -Format o)" | Out-File -Append -Encoding utf8 $log
