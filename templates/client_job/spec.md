# 案件仕様（ここに依頼文をそのまま貼る → Claude Code に「spec.mdを実装して」）

## 依頼内容（原文）


## 入力
- ファイル: in/ に置く（例: 毎日届くCSV / PDF請求書 / Excel）
- 形式・サンプル:

## 出力
- 例: out/集計_YYYYMMDD.xlsx / スプレッドシート / Slack通知

## 実行方法の希望
- [ ] ダブルクリックで動くexe   - [ ] GAS（PCに何も入れない）   - [ ] 毎日自動（タスクスケジューラ）

## 実装メモ（Claude Code向け）
- まず `officeworker` のレシピ（YAML）で書けるか検討。足りなければ main.py に書く
- 使える部品: officeworker.io.read_any/write_any, officeworker.pdf.invoice/tables, officeworker.sheets.push, officeworker.notify.send
- 納品は `python -m officeworker build main.py --name ツール名` で exe 化
