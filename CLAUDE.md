# office-worker
- 再開時は `docs/HANDOFF.md` と `docs/BUSINESS_ARCHITECTURE.md` を読む。基本導入は submodule 不要、OpenHands は `setup.ps1 -WithAgent`。検証は `pip install -r requirements-dev.txt` → `python -m unittest discover -s tests -v`。
- 実行: `python -m officeworker <cmd>`。エントリ `officeworker/__main__.py`
- 業務フローは `recipes/*.yaml`。ステップ追加は `officeworker/recipe.py` に `@step("name")` 関数 `(df, arg, ctx) -> df`
- 部品: `io.read_any/read_many/write_any`（文字コード自動）, `pdf.invoice/tables/text`, `sheets.push/pull`, `notify.send`, `llm.ask`
- 受託案件は `jobs/<name>/`（gitignore対象）。`spec.md` を読んで `main.py` を実装、まずレシピで足りるか検討
- exe 納品は `python -m officeworker build main.py --name X`。exe内では `BASE` 基準でパス解決
- HTTP API は `officeworker/server.py`（FastAPI）。n8n フローは `n8n/workflows/*.json` → `scripts/n8n.ps1 up` で取込
- `agent` コマンドは `officeworker/agent.py`。OpenHands SDK は `vendor/openhands-sdk`（submodule・改変しない）
- 商品は `products/<名前>/`（recipe.yaml・run.py・説明書・検収条件・sample/expected.json）。検収は `tests/test_product_*.py`
