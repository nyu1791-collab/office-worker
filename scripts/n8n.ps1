# n8n を起動し、n8n/workflows のフローを取り込む。要 Docker Desktop
#   .\scripts\n8n.ps1 up | import | down | logs
param([string]$cmd = "up")
$root = (Resolve-Path "$PSScriptRoot\..").Path
$dc = @("compose", "-f", "$root\docker\n8n\docker-compose.yml")
switch ($cmd) {
  "up"     { docker @dc up -d; Start-Sleep 8; docker @dc exec n8n n8n import:workflow --separate --input=/workflows; Write-Host "n8n: http://localhost:5678 （APIは別窓で python -m officeworker serve）" }
  "import" { docker @dc exec n8n n8n import:workflow --separate --input=/workflows }
  "down"   { docker @dc down }
  "logs"   { docker @dc logs -f n8n }
}
