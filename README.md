# office-worker — 事務作業（CSV / PDF / Excel / スプレッドシート）丸投げ自動化キット

クラウドソーシングの「業務自動化」案件を **30分〜1時間で納品** するための部品箱＋工場。

- **レシピ（YAML）** を並べるだけで「読む→整える→集計→保存→シート→通知→退避」が組める（n8n のノードを YAML にした感じ）
- 日本の現場特有の **Shift_JIS CSV / 請求書PDF / インボイス番号 / Chatwork** に最初から対応
- 案件ごとに `new` で雛形 → Claude Code に `spec.md` を実装させる → `build` で exe 納品
- 「PCに何も入れたくない」依頼主向けの **GAS テンプレ** 付き

## 参考にした仕組み
| 元ネタ | 取り込んだ部分 |
|---|---|
| [n8n](https://github.com/n8n-io/n8n) | ノードを繋ぐワークフロー → YAMLステップ化、トリガー（フォルダ監視・スケジュール） |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) / Claude Code | `jobs/<案件>/spec.md` を渡して自律実装させる「工場」運用 |
| pdfplumber / camelot 系 | PDF表抽出、請求書は Gemini 構造化＋正規表現フォールバック |
| 各種 GAS スニペット集 | フォーム自動返信・Gmail添付保存・CSV取込・シート内AI関数 |

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

## 受託の回し方（目安 1案件 30〜60分）
1. `templates/proposals/` の提案文で応募（Claude に募集文と一緒に渡して埋めさせる）
2. 受注 → `python -m officeworker new 顧客名_内容` → `spec.md` に依頼文を貼る
3. `cd jobs/顧客名_内容 ; claude` →「spec.md を実装して、in/ のサンプルで動作確認まで」
4. `python -m officeworker build main.py --name ツール名` → exe と `README_納品.md` を zip で納品
5. PCに入れたくない依頼主 → `templates/gas/` を貼って調整
