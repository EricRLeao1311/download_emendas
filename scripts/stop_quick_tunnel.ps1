$pidFile = Join-Path $PSScriptRoot "..\\data\\tmp\\cloudflared.pid"

if (-not (Test-Path $pidFile)) {
  Write-Error "Arquivo de PID do cloudflared nao encontrado."
  exit 1
}

$pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue
if (-not $pidValue) {
  Write-Error "PID do cloudflared nao encontrado."
  exit 1
}

Stop-Process -Id ([int]$pidValue) -Force -ErrorAction Stop
Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
Write-Host "Tunel encerrado."
