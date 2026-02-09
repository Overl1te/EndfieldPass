param(
  [string]$LogPath = "$env:USERPROFILE\AppData\LocalLow\Gryphline\Endfield\sdklogs\HGWebview.log",
  [int]$TailLines = 50000,
  [switch]$NoClipboard
)

$ErrorActionPreference = 'Stop'

function Get-LastGachaHistoryUrl {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][int]$Tail
  )

  if (-not (Test-Path $Path)) {
    throw ("Log file not found: " + $Path)
  }

  $lines = Get-Content -Path $Path -Tail $Tail -ErrorAction Stop
  $pattern = [regex]'https://ef-webview\.gryphline\.com/page/gacha_char\?[^\s"]+'

  $last = $null
  foreach ($line in $lines) {
    $m = $pattern.Match($line)
    if ($m.Success) { $last = $m.Value }
  }

  if (-not $last) {
    throw "Gacha history URL not found in the log. Open the gacha history screen in-game, then run the script again."
  }

  return $last
}

try {
  $url = Get-LastGachaHistoryUrl -Path $LogPath -Tail $TailLines

  # 1) Print the extracted Endfield URL as a single line (easy to copy/paste / pipe)
  Write-Output $url

  # 2) Copy to clipboard (default) and print a highlighted, clickable site link
  $site = 'https://endfieldpass.com'

  if (-not $NoClipboard) {
    Set-Clipboard -Value $url

    Write-Host ''
    Write-Host '========================================' -ForegroundColor Green
    Write-Host '✅ Ссылка скопирована в буфер обмена.' -ForegroundColor Green
    Write-Host 'Вставьте её на:' -ForegroundColor Green
    Write-Host $site -ForegroundColor Cyan
    Write-Host '========================================' -ForegroundColor Green
  } else {
    Write-Host ''
    Write-Host '========================================' -ForegroundColor Yellow
    Write-Host '⚠️ Ссылка извлечена, но не скопирована.' -ForegroundColor Yellow
    Write-Host 'Причина: запущено с параметром -NoClipboard.' -ForegroundColor Yellow
    Write-Host 'Вставьте её на:' -ForegroundColor Yellow
    Write-Host $site -ForegroundColor Cyan
    Write-Host '========================================' -ForegroundColor Yellow
  }
}
catch {
  Write-Host ("[ERROR] " + $_.Exception.Message) -ForegroundColor Red
  exit 1
}
