# Optional bridge: watch a folder for "notify markers" and run on-notify pull.
#
# Use cases:
#   - Power Automate / IFTTT / ntfy / custom script drops a file when Discord pings
#   - Forward bot on YOUR server writes a stamp file on new mirrored message
#   - You manually touch a file when you see a callout
#
# Example:
#   pwsh -File scripts/kol_notify_watch_folder.ps1
#   # then: New-Item data\kol_notify_inbox\ping.txt
#
# File name may encode channel id:
#   123456789012345678.ping  →  pulls only that channel
#   any.other.name           →  pulls all channels in kol_channels.txt

param(
  [string]$RepoRoot = "C:\Users\niko\Desktop\智能交易系统",
  [string]$Inbox = "data\kol_notify_inbox",
  [string]$SystemSide = "BTC/USDT=long",
  [int]$PollMs = 1500,
  [int]$DebounceSeconds = 45
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
Set-Location $RepoRoot

$inboxPath = Join-Path $RepoRoot $Inbox
if (-not (Test-Path $inboxPath)) {
  New-Item -ItemType Directory -Path $inboxPath -Force | Out-Null
  Write-Host "[watch] created $inboxPath — drop any file to trigger pull"
}

$processed = Join-Path $inboxPath "_processed"
if (-not (Test-Path $processed)) {
  New-Item -ItemType Directory -Path $processed -Force | Out-Null
}

Write-Host "[watch] watching $inboxPath (Ctrl+C to stop)"

while ($true) {
  $files = Get-ChildItem -Path $inboxPath -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike ".*" }
  foreach ($f in $files) {
    $name = $f.BaseName
    $channelArg = @()
    if ($name -match '^\d{15,22}$') {
      $channelArg = @("-ChannelId", $name)
      Write-Host "[watch] trigger channel=$name from $($f.Name)"
    } else {
      Write-Host "[watch] trigger ALL from $($f.Name)"
    }

    try {
      & (Join-Path $RepoRoot "scripts\kol_on_notify_pull.ps1") @channelArg `
        -RepoRoot $RepoRoot -SystemSide $SystemSide -DebounceSeconds $DebounceSeconds
    } catch {
      Write-Warning $_
    }

    $dest = Join-Path $processed ("{0}_{1}" -f (Get-Date -Format "yyyyMMddHHmmss"), $f.Name)
    Move-Item -Path $f.FullName -Destination $dest -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Milliseconds $PollMs
}
