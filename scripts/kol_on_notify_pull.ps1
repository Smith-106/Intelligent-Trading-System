# Event-triggered near-realtime KOL pull (notify → debounce → incremental export → ingest).
#
# Idea:
#   When a Discord channel you care about "updates" (desktop toast, forward webhook,
#   file drop, or any external signal), call this script. It:
#     1) debounces bursts (default 45s)
#     2) exports only messages after last successful cursor (--after)
#     3) runs ingest + consensus + reference
#
# This is still NOT an official Discord Gateway consumer.
# User-token DCE automation violates Discord ToS — risk is yours.
# Prefer admin bot poll when available. Never commit tokens.
#
# Examples:
#   # Manual / toast-hook / webhook receiver:
#   pwsh -File scripts/kol_on_notify_pull.ps1
#
#   # Only one channel (if the notifier knows which):
#   pwsh -File scripts/kol_on_notify_pull.ps1 -ChannelId 123456789012345678
#
#   # Force full re-export for listed channels (ignore cursor):
#   pwsh -File scripts/kol_on_notify_pull.ps1 -Full
#
# Windows: pair with Power Automate / BurntToast log / webhook listener that
# runs this script with -Once semantics (this script always one-shot).

param(
  [string]$RepoRoot = "C:\Users\niko\Desktop\智能交易系统",
  [string]$DceCli = "DiscordChatExporter.Cli",
  [string]$ChannelList = "scripts\kol_channels.txt",
  [string]$ExportDir = "data\kol_exports",
  [string]$CursorFile = "data\kol_signals\export_cursors.json",
  [string]$LockFile = "data\kol_signals\on_notify.lock",
  [string]$DebounceState = "data\kol_signals\on_notify_debounce.json",
  [string]$SystemSide = "BTC/USDT=long",
  [string]$ChannelId = "",
  [int]$DebounceSeconds = 45,
  [int]$MediaDelayMs = 200,
  [int]$LookbackMinutes = 5,
  [switch]$Full,
  [switch]$SkipDownload,
  [switch]$SkipIngest,
  [switch]$SkipImages,
  [switch]$SkipExport
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
Set-Location $RepoRoot

function Ensure-Parent([string]$Path) {
  $dir = Split-Path $Path -Parent
  if ($dir -and -not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
  }
}

function Get-Token {
  $t = $env:DISCORD_USER_TOKEN
  if (-not $t) { $t = $env:DCE_TOKEN }
  if (-not $t) {
    throw "Set DISCORD_USER_TOKEN (or DCE_TOKEN) in the environment. Do not put it in git."
  }
  return $t
}

function Get-Channels {
  if ($ChannelId) { return @($ChannelId.Trim()) }
  $path = Join-Path $RepoRoot $ChannelList
  if (-not (Test-Path $path)) {
    throw "Missing $path — fill channel IDs or pass -ChannelId"
  }
  $ids = Get-Content $path | ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith("#") }
  if (-not $ids) { throw "No channel IDs in $path" }
  return @($ids)
}

function Read-JsonMap([string]$Path) {
  if (-not (Test-Path $Path)) { return @{} }
  try {
    $raw = Get-Content $Path -Raw -Encoding UTF8
    if (-not $raw.Trim()) { return @{} }
    $obj = $raw | ConvertFrom-Json
    $map = @{}
    foreach ($p in $obj.PSObject.Properties) {
      $map[$p.Name] = $p.Value
    }
    return $map
  } catch {
    Write-Warning "cursor read failed: $_"
    return @{}
  }
}

function Write-JsonMap([string]$Path, $Map) {
  Ensure-Parent $Path
  ($Map | ConvertTo-Json -Depth 6) | Set-Content -Path $Path -Encoding UTF8
}

function Try-AcquireLock {
  $path = Join-Path $RepoRoot $LockFile
  Ensure-Parent $path
  if (Test-Path $path) {
    $age = (Get-Date) - (Get-Item $path).LastWriteTime
    if ($age.TotalMinutes -lt 15) {
      Write-Host "[on-notify] another pull holds lock ($([int]$age.TotalSeconds)s old) — skip"
      return $false
    }
    Write-Warning "[on-notify] stale lock removed"
    Remove-Item $path -Force -ErrorAction SilentlyContinue
  }
  "pid=$PID ts=$((Get-Date).ToString('o'))" | Set-Content $path -Encoding UTF8
  return $true
}

function Release-Lock {
  $path = Join-Path $RepoRoot $LockFile
  if (Test-Path $path) { Remove-Item $path -Force -ErrorAction SilentlyContinue }
}

function Should-Debounce {
  $path = Join-Path $RepoRoot $DebounceState
  Ensure-Parent $path
  $now = Get-Date
  if (Test-Path $path) {
    try {
      $st = Get-Content $path -Raw | ConvertFrom-Json
      $last = [datetime]::Parse($st.last_fire)
      $delta = ($now - $last).TotalSeconds
      if ($delta -lt $DebounceSeconds) {
        Write-Host "[on-notify] debounce: last fire ${delta}s ago < ${DebounceSeconds}s — skip"
        return $true
      }
    } catch {}
  }
  @{ last_fire = $now.ToString("o"); reason = "notify" } | ConvertTo-Json |
    Set-Content $path -Encoding UTF8
  return $false
}

function Get-AfterIso([string]$Ch, $Cursors) {
  if ($Full) { return $null }
  if ($Cursors.ContainsKey($Ch) -and $Cursors[$Ch].last_after) {
    return [string]$Cursors[$Ch].last_after
  }
  # First run: only recent window to avoid huge history
  return (Get-Date).ToUniversalTime().AddMinutes(-[Math]::Max(1, $LookbackMinutes)).ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function Invoke-DceExport {
  param(
    [string]$ChannelId,
    [string]$Token,
    [string]$OutFile,
    [string]$AfterIso
  )

  $args = @(
    "export",
    "-t", $Token,
    "-c", $ChannelId,
    "-f", "Json",
    "-o", $OutFile
  )
  if ($AfterIso) {
    $args += @("--after", $AfterIso)
  }
  if (-not $SkipDownload) {
    $media = Join-Path $RepoRoot "$ExportDir\media\$ChannelId"
    $args += @("--media", "--media-dir", $media, "--media-delay", "$MediaDelayMs")
  }

  Write-Host "[on-notify] DCE channel=$ChannelId after=$AfterIso -> $OutFile"
  & $DceCli @args
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "DCE exit $LASTEXITCODE for $ChannelId"
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

# --- main ---
Write-Host "[on-notify] start Full=$Full ChannelId='$ChannelId' debounce=${DebounceSeconds}s"

if (Should-Debounce) { exit 0 }
if (-not (Try-AcquireLock)) { exit 0 }

try {
  $outDir = Join-Path $RepoRoot $ExportDir
  if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
  }

  $cursorPath = Join-Path $RepoRoot $CursorFile
  $cursors = Read-JsonMap $cursorPath
  $channels = Get-Channels
  $ok = 0
  $nowIso = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

  if (-not $SkipExport) {
    $token = Get-Token
    foreach ($ch in $channels) {
      $after = Get-AfterIso $ch $cursors
      $out = Join-Path $outDir "$ch.json"
      if (Invoke-DceExport -ChannelId $ch -Token $token -OutFile $out -AfterIso $after) {
        $ok++
        # Advance cursor to "now" so next notify only pulls newer
        $cursors[$ch] = @{
          last_after = $nowIso
          last_ok    = $nowIso
          last_file  = $out
        }
      }
    }
    Write-JsonMap $cursorPath $cursors
    Write-Host "[on-notify] exported $ok / $($channels.Count)"
  } else {
    Write-Host "[on-notify] SkipExport — ingest only"
  }

  if (-not $SkipIngest) {
    Invoke-IngestTick
  }
}
finally {
  Release-Lock
}

Write-Host "[on-notify] done"
exit 0
