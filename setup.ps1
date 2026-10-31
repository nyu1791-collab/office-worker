# Windows: .\setup.ps1（追加機能は下のスイッチで導入）
param([switch]$WithAgent, [switch]$WithMedia, [switch]$WithManga, [switch]$WithDiary)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-Checked {
  param([string]$Program, [string[]]$CommandArgs)
  & $Program @CommandArgs
  if ($LASTEXITCODE -ne 0) { throw "$Program の実行に失敗しました（終了コード: $LASTEXITCODE）" }
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python 3.12以上をインストールし、PowerShellを開き直してください"
}
# 二重引用符を含まない引数にし、Windows PowerShell 5.1でも同じコードを渡す。
Invoke-Checked -Program "python" -CommandArgs @("-c", 'import sys; sys.exit(int(sys.version_info < (3, 12)))')
Invoke-Checked -Program "python" -CommandArgs @("-m", "venv", ".venv")
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Invoke-Checked -Program $venvPython -CommandArgs @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Checked -Program $venvPython -CommandArgs @("-m", "pip", "install", "-r", "requirements.txt")
if ($WithAgent) {
  Invoke-Checked -Program "git" -CommandArgs @("submodule", "update", "--init", "--depth", "1", "vendor/openhands-sdk")
  Invoke-Checked -Program $venvPython -CommandArgs @("-m", "pip", "install", "-r", "requirements-agent.txt")
}
# 事業ごとの追加: -WithMedia（モザイク・切り抜き）/ -WithManga（翻訳写植）/ -WithDiary（写メ日記）
foreach ($pair in @(@($WithMedia, "requirements-media.txt"), @($WithManga, "requirements-manga.txt"), @($WithDiary, "requirements-diary.txt"))) {
  if ($pair[0]) { Invoke-Checked -Program $venvPython -CommandArgs @("-m", "pip", "install", "-r", $pair[1]) }
}
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
Write-Host "完了。以後は .\.venv\Scripts\Activate.ps1 してから使います"
