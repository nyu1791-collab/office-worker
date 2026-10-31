# n8n を Docker なしで起動（Node.js が必要: winget install OpenJS.NodeJS.LTS）。メモリ 0.3〜0.5GB
#   .\scripts\n8n-local.ps1          … 初回はワークフローを取り込んでから起動 → http://localhost:5678
#   .\scripts\n8n-local.ps1 import   … ワークフローの取り込みだけ
param([string]$cmd = "up")
$root = (Resolve-Path "$PSScriptRoot\..").Path
$env:GENERIC_TIMEZONE = "Asia/Tokyo"
$env:N8N_DIAGNOSTICS_ENABLED = "false"
$env:N8N_BLOCK_ENV_ACCESS_IN_NODE = "false"   # ワークフローから OW_API_TOKEN / OW_API_URL を読む
if (Test-Path "$root\.env") {
  Get-Content "$root\.env" | Where-Object { $_ -match '^(OW_API_TOKEN|OW_API_URL)=(.*)$' } | ForEach-Object {
    Set-Item -Path "env:$($Matches[1])" -Value $Matches[2]
  }
}
$flag = Join-Path $env:USERPROFILE ".n8n\.officeworker_imported"
if ($cmd -eq "import" -or -not (Test-Path $flag)) {
  npx --yes n8n import:workflow --separate --input="$root\n8n\workflows"
  New-Item -ItemType File -Force $flag | Out-Null
  if ($cmd -eq "import") { exit }
}
Write-Host "n8n: http://localhost:5678 （API は別窓で python -m officeworker serve）"
npx --yes n8n start
