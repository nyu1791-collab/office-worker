# Windows 初回セットアップ:  PowerShell で  .\setup.ps1
# 実行ポリシーで止まる場合:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  Write-Host "Python を入れました。PowerShell を開き直して再実行してください"; exit
}
python -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\pip install -r requirements.txt
if (Select-String -Path requirements.txt -Pattern '^playwright' -Quiet) { .\.venv\Scripts\python -m playwright install chromium }
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host ".env を作成しました。APIキーを書き込んでください" }
Write-Host "完了。以後は  .\.venv\Scripts\Activate.ps1  してから使います"
