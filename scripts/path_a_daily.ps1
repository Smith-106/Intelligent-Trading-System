# Path A daily credit helper (T023 wall-clock).
# Run once per UTC day from repo root. Does NOT backfill past/future dates.
#   pwsh -File scripts/path_a_daily.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONUTF8 = "1"

Write-Host "[path_a_daily] UTC date: $((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd'))"
python scripts/paper_day_streak.py ingest --run-day-session
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/paper_day_streak.py status --min-days 7
exit $LASTEXITCODE
