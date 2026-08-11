# Near-realtime KOL tick for paid members (no Discord bot).
# Schedule every 2-5 minutes via Task Scheduler.
# Prerequisites: DiscordChatExporter (or other) already writing JSON under ExportDir.

param(
  [string]$RepoRoot = "C:\Users\niko\Desktop\智能交易系统",
  [string]$ExportDir = "data\kol_exports",
  [string]$SystemSide = "BTC/USDT=long",
  [switch]$SkipImages
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
Set-Location $RepoRoot

$exportPath = Join-Path $RepoRoot $ExportDir
if (-not (Test-Path $exportPath)) {
  New-Item -ItemType Directory -Path $exportPath | Out-Null
  Write-Host "[kol-tick] created $exportPath — drop channel JSON exports here"
}

$jsonFiles = Get-ChildItem -Path $exportPath -Filter *.json -File -ErrorAction SilentlyContinue
if (-not $jsonFiles) {
  Write-Host "[kol-tick] no JSON in $exportPath — run DiscordChatExporter first"
  exit 0
}

foreach ($f in $jsonFiles) {
  $args = @(".\scripts\kol_discord_ingest.py", "export", $f.FullName)
  if (-not $SkipImages) { $args += @("--images", "--ocr", "auto") }
  else { $args += @("--ocr", "none") }
  Write-Host "[kol-tick] export $($f.Name)"
  & python @args
  if ($LASTEXITCODE -ne 0) { Write-Warning "export failed: $($f.Name) code=$LASTEXITCODE" }
}

Write-Host "[kol-tick] consensus"
& python .\scripts\kol_discord_ingest.py consensus --window-hours 6 --min-sources 2
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[kol-tick] reference"
& python .\scripts\kol_discord_ingest.py reference --system-side $SystemSide
exit $LASTEXITCODE
