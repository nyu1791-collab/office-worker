# 売上集計ツールの exe を作る（Windows / リポジトリの .venv を有効化してから）
# 出力: dist\売上集計\売上集計.exe と recipe.yaml, in\, out\
$here = $PSScriptRoot
$repo = (Resolve-Path "$here\..\..").Path
if (-not (Test-Path "$repo\officeworker")) { $repo = (Resolve-Path "$here\..\..\..").Path }  # jobs\<案件>\ から実行した場合
python -m PyInstaller --noconfirm --clean --onefile --name 売上集計 `
  --paths $repo --add-data "$here\recipe.yaml;." `
  --exclude-module google.genai --exclude-module gspread --exclude-module fastapi `
  --distpath "$here\dist\売上集計" --workpath "$here\build" --specpath "$here\build" "$here\run.py"
Copy-Item "$here\recipe.yaml" "$here\dist\売上集計\" -Force
New-Item -ItemType Directory -Force "$here\dist\売上集計\in", "$here\dist\売上集計\out" | Out-Null
Write-Host "完了: $here\dist\売上集計"
