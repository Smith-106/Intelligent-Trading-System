# Periodic "near-realtime export" for paid Discord members (no bot invite).
#
# What this is:
#   Polling export every N minutes via DiscordChatExporter CLI (user session),
#   then QuantFlow ingest → consensus → optional reference weights.
# What this is NOT:
#   Official live Gateway / compliant second-level stream.
#   User-token automation violates Discord ToS — use at your own risk;
#   prefer admin read-only bot when available. Do not commit tokens.
#
# Prerequisites:
#   1) Download DiscordChatExporter CLI:
#      https://github.com/Tyrrrz/DiscordChatExporter/releases
#   2) Set env DISCORD_USER_TOKEN only in your machine user env / Task Scheduler
#      (never commit, never put in repo files).
#   3) Fill channel IDs in scripts/kol_channels.txt (one snowflake per line).
#
# Example (one shot):
#   pwsh -File scripts/kol_export_loop.ps1 -Once
#
# Example (loop every 3 min until Ctrl+C):
#   pwsh -File scripts/kol_export_loop.ps1 -IntervalMinutes 3
#
# Task Scheduler: run with -Once every 2–5 minutes.

param(
  [string]$RepoRoot = "C:\Users\niko\Desktop\智能交易系统",
  [string]$DceCli = "DiscordChatExporter.Cli",  # or full path to .exe
  [string]$ChannelList = "scripts\kol_channels.txt",
  [string]$ExportDir = "data\kol_exports",
  [string]$SystemSide = "BTC/USDT=long",
  [int]$IntervalMinutes = 3,
  [int]$MediaDelayMs = 200,
  [switch]$Once,
  [switch]$SkipDownload,
  [switch]$SkipIngest,
  [switch]$SkipImages
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
Set-Location $RepoRoot

function Get-Token {
  $t = $env:DISCORD_USER_TOKEN
  if (-not $t) { $t = $env:DCE_TOKEN }
  if (-not $t) {
    throw "Set DISCORD_USER_TOKEN (or DCE_TOKEN) in the environment. Do not put it in git."
  }
  return $t
}

function Get-Channels {
  $path = Join-Path $RepoRoot $ChannelList
  if (-not (Test-Path $path)) {
    $sample = @"
# One Discord channel snowflake ID per line (Developer Mode → Copy Channel ID)
# Example:
# 123456789012345678
"@
    $dir = Split-Path $path -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    Set-Content -Path $path -Value $sample -Encoding UTF8
    throw "Created $path — fill channel IDs then re-run."
  }
  $ids = Get-Content $path | ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith("#") }
  if (-not $ids) { throw "No channel IDs in $path" }
  return $ids
}

function Invoke-DceExport {
  param([string]$ChannelId, [string]$Token, [string]$OutFile)

  $args = @(
    "export",
    "-t", $Token,
    "-c", $ChannelId,
    "-f", "Json",
    "-o", $OutFile
  )
  if (-not $SkipDownload) {
    $args += @("--media", "--media-dir", (Join-Path $RepoRoot "$ExportDir\media\$ChannelId"))
    $args += @("--media-delay", "$MediaDelayMs")
  }

  Write-Host "[dce] channel=$ChannelId -> $OutFile"
  & $DceCli @args
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "DCE exit $LASTEXITCODE for channel $ChannelId"
    return $false
  }
  return $true
}

function Invoke-IngestTick {
  $tick = Join-Path $RepoRoot "scripts\kol_near_realtime_tick.ps1"
  $tickArgs = @{
    RepoRoot   = $RepoRoot
    ExportDir  = $ExportDir
    SystemSide = $SystemSide
  }
  if ($SkipImages) { $tickArgs.SkipImages = $true }
  & $tick @tickArgs
}

function Invoke-OneCycle {
  $token = Get-Token
  $channels = Get-Channels
  $outDir = Join-Path $RepoRoot $ExportDir
  if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir | Out-Null
  }

  $ok = 0
  foreach ($ch in $channels) {
    $out = Join-Path $outDir "$ch.json"
    if (Invoke-DceExport -ChannelId $ch -Token $token -OutFile $out) { $ok++ }
  }
  Write-Host "[dce] exported $ok / $($channels.Count) channels"

  if (-not $SkipIngest) {
    Invoke-IngestTick
  }
}

Write-Host "[kol-export-loop] root=$RepoRoot interval=${IntervalMinutes}m once=$Once"
if ($Once) {
  Invoke-OneCycle
  exit 0
}

while ($true) {
  try {
    Invoke-OneCycle
  } catch {
    Write-Warning $_
  }
  Write-Host "[kol-export-loop] sleep $IntervalMinutes min..."
  Start-Sleep -Seconds ([Math]::Max(30, $IntervalMinutes * 60))
}
