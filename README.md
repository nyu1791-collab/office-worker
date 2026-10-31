# office-worker — 事務作業（CSV / PDF / Excel / スプレッドシート）丸投げ自動化キット

クラウドソーシングの「業務自動化」案件を **30分〜1時間で納品** するための部品箱＋工場。

- **レシピ（YAML）** を並べるだけで「読む→整える→集計→保存→シート→通知→退避」が組める（n8n のノードを YAML にした感じ）
- 日本の現場特有の **Shift_JIS CSV / 請求書PDF / インボイス番号 / Chatwork** に最初から対応
- 案件ごとに `new` で雛形 → Claude Code に `spec.md` を実装させる → `build` で exe 納品
- 「PCに何も入れたくない」依頼主向けの **GAS テンプレ** 付き

## 取り込んだリポジトリ
| 元リポジトリ | 取り込み方 | このキットでの役割 |
|---|---|---|
| [OpenHands/software-agent-sdk](https://github.com/OpenHands/software-agent-sdk)（OpenHands 本体のエージェントSDK, MIT） | `vendor/openhands-sdk`（git submodule, v1.59.0）を editable install | `agent` コマンド: `spec.md` を渡すとターミナル＋ファイル編集ツールで自律実装・実行確認（Gemini で動く） |
| [n8n-io/n8n](https://github.com/n8n-io/n8n) | 公式 Docker イメージ + `n8n/workflows/*.json` を自動インポート | Gmail・定時・Webhook のトリガー → officeworker API を呼ぶ |
| Claude Code / [opencode](https://github.com/sst/opencode) | CLI があれば `agent --engine claude/opencode` で同じ流れ | OpenHands の代替エンジン |
| pdfplumber / pandas / gspread | ライブラリ | PDF表・請求書・Excel・シート |

## 最短スタート（Windows）
```powershell
.\setup.ps1
.\.venv\Scripts\Activate.ps1
python -m officeworker run recipes\merge_sales.yaml     # サンプルで動作確認（APIキー不要）
```

## コマンド
| コマンド | 内容 |
|---|---|
| `run recipes/x.yaml [--var k=v]` | レシピ実行 |
| `watch in/ recipes/x.yaml` | フォルダに新ファイルが来たら自動実行 |
| `merge "in/*.csv" -o out/all.xlsx` | 複数CSV/Excel統合（文字コード自動） |
| `invoice "in/*.pdf" -o out/inv.xlsx` | 請求書PDF → 一覧（発行元/番号/日付/金額/T番号/振込先） |
| `pdf file.pdf -o out.csv` | PDF内の表を抽出 |
| `tosheet file.csv --tab 名前 [--append]` | スプレッドシート反映 |
| `notify "本文" [--attach file]` | Slack / Discord / Chatwork / メール |
| `new 案件名` | `jobs/案件名/` に雛形（spec.md・main.py・納品README） |
| `agent jobs/案件名 [--engine openhands/claude/opencode]` | spec.md を AI が自動実装→実行確認→DONE.md |
| `serve [--port 8765]` | HTTP API（`/docs` で試せる。n8n・GAS から呼ぶ） |
| `build main.py --name ツール名` | exe 化 → `dist/` |

毎日自動: `.\scripts\schedule_task.ps1 -Recipe recipes\invoices_to_excel.yaml -Time 09:00`

## レシピのステップ一覧
`load` `invoices` `pdf_tables` `rename` `select` `filter` `dedupe` `sort` `derive` `to_number` `to_date` `groupby` `join` `ai` `save` `sheet` `notify` `move` `print`
（パスには `{date}` `{month}` `{datetime}`、通知文には `{rows}` `{file}` `{sheet_url}` が使える）

```yaml
name: 請求書PDF→一覧
steps:
  - invoices: in/*.pdf
  - save: out/請求書一覧_{date}.xlsx
  - sheet: {tab: 請求書, mode: append}
  - notify: {text: "請求書 {rows} 件を処理: {file}", attach: true}
  - move: {files: in/*.pdf, to: "archive/{month}"}
```
新しいステップは `officeworker/recipe.py` に `@step("名前")` の関数を1つ足すだけ。

## n8n 連携（ノーコードのトリガー × Python の処理）
```powershell
python -m officeworker serve          # 窓1: API（http://localhost:8765/docs）
.\scripts\n8n.ps1 up                  # 窓2: n8n 起動＋下記フローを自動取込 → http://localhost:5678
```
| フロー | 内容 |
|---|---|
| 01_schedule_recipe | 平日9時に `recipes/invoices_to_excel.yaml` を実行 |
| 02_gmail_invoice | Gmail の請求書PDFを1時間ごと取得 → `/invoice` で抽出 → シート「請求書」追記 → 通知（Gmail 認証だけ n8n 上で設定） |
| 03_webhook_ai | `POST /webhook/ow-ai {"text": ...}` → AI 分類・要約して返す |
| 04_form_to_sheet | `POST /webhook/ow-merge`（CSV/Excel 添付）→ 統合 → シート → 通知 |

API: `/run/{レシピ名}` `/invoice` `/merge` `/pdf-tables` `/ai` `/notify`（`.env` の `OW_API_TOKEN` を設定すると `x-token` ヘッダ必須）

## 受託の回し方（目安 1案件 30〜60分）
1. `templates/proposals/` の提案文で応募（Claude に募集文と一緒に渡して埋めさせる）
2. 受注 → `python -m officeworker new 顧客名_内容` → `spec.md` に依頼文を貼る
3. `python -m officeworker agent jobs/顧客名_内容` → OpenHands（または Claude Code）が実装・実行確認・説明書まで作り `DONE.md` に報告
4. `python -m officeworker build main.py --name ツール名` → exe と `README_納品.md` を zip で納品
5. PCに入れたくない依頼主 → `templates/gas/` を貼って調整
