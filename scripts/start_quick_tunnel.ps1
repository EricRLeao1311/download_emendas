param(
  [int]$Port = 8501,
  [string]$Host = "127.0.0.1"
)

$localBinary = Join-Path $PSScriptRoot "..\\tools\\cloudflared\\cloudflared.exe"
$cloudflaredPath = $null

if (Test-Path $localBinary) {
  $cloudflaredPath = (Resolve-Path $localBinary).Path
} else {
  $cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
  if ($cloudflared) {
    $cloudflaredPath = $cloudflared.Source
  }
}

if (-not $cloudflaredPath) {
  Write-Error "cloudflared nao encontrado. Baixe em tools\\cloudflared\\cloudflared.exe ou instale com winget e rode este script de novo."
  exit 1
}

$url = "http://$Host`:$Port"
Write-Host "Abrindo tunel publico para $url"
Write-Host "Quando a URL trycloudflare aparecer, pode compartilhar com quem vai testar."
& $cloudflaredPath tunnel --url $url
