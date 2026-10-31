# レシピを毎日自動実行するタスクを Windows タスクスケジューラに登録
# 例: .\scripts\schedule_task.ps1 -Recipe recipes\invoices_to_excel.yaml -Time 09:00
param([string]$Recipe, [string]$Time = "09:00", [string]$Name = "officeworker")
$dir = (Resolve-Path "$PSScriptRoot\..").Path
$py = "$dir\.venv\Scripts\python.exe"
$action = New-ScheduledTaskAction -Execute $py -Argument "-m officeworker run $Recipe" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
Register-ScheduledTask -TaskName "$Name-$(Split-Path $Recipe -LeafBase)" -Action $action -Trigger $trigger -Force
Write-Host "登録しました: 毎日 $Time に $Recipe"
