# office-worker 引き継ぎ

## 目的と実装済みの範囲

事業1の受託・再利用用部品です。YAMLレシピでCSV/Excel/PDFの読み込み、整形、集計、保存、Sheets連携、通知、退避を組み合わせます。CLI、FastAPI、n8nフローの雛形、GAS雛形、案件フォルダ作成、AI実装支援、exe化の入口まであります。

[3リポジトリ全体の構成・合併判断](BUSINESS_ARCHITECTURE.md)を参照してください。動画リポジトリは対象外です。

## 今回の修正

- CSV/PDFをファイルごとに処理し、失敗は `error.log` と失敗一覧に残して続行。全件失敗は明示エラー。
- レシピの `move` は読み取りに失敗したファイルを退避しない。
- APIアップロードはリクエストごと・ファイルごとに分離。同名の添付でも上書きしない。
- APIの出力先を `OW_ROOT` 内に制限。Excel書き込みはロック。
- 全角の請求額を正規化し、抽出額の切り詰めを修正。
- 空白PDFはOCR未対応として入力に残し、金額0は欠損と区別して保持。
- OpenHandsの導入は `setup.ps1 -WithAgent` / `setup.sh --with-agent` を指定した時だけ。
- 回帰テストとGitHub Actionsのテスト実行を追加。

## 再開コマンド

リポジトリ直下でPython 3.12以上を使います。

```powershell
.\setup.ps1
.\.venv\Scripts\python -m officeworker run recipes\merge_sales.yaml
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m unittest discover -s tests -v
```

売上サンプルの期待結果は明細5行、店舗別3行。池袋=2900、渋谷=2700、新宿=800です。出力Excelには「明細」「店舗別」の2シートができます。既定環境で実行して、この集計を確認しました。

Python 3.12の専用venvに基本依存とテスト依存を新規導入し、回帰テスト13件、売上サンプル、`pip check` を確認しました。

Linuxでは `bash setup.sh` の後に `.venv/bin/python` で同じコマンドを実行できます。

## 失敗の確認

CLIでは実行ログと `error.log`、Pythonからは `df.attrs["failed_files"]`、レシピからは `ctx["failed_files"]` を確認します。APIは `failed_files` を返し、全件読み取り失敗はHTTP 422、入力なしは400です。部分成功を完全成功と扱わず、入力に残った失敗ファイルを修正して再処理してください。

## 未確認・制約

Windows/PowerShellでのセットアップ実行は今回未検証です。

実際のGemini、Sheets、各通知サービス、OpenHands、Docker/n8n、Windowsでのexe実行は今回未検証です。画像だけのPDFはOCR未対応です。AI抽出した金額も原本と検収します。

n8nは雛形で、認証・URL・必要に応じた `x-token` ヘッダーの設定とフローの有効化が必要です。Gmail請求書フローは現在 `attachment_0` だけを扱い、全添付の処理・再取り込み防止は未実装です。Sheets追記と通知を含む処理全体は取引として巻き戻せないため、同じ入力の再実行では重複を確認します。

顧客ファイルは `in/`、`out/`、`archive/`、`jobs/` に置き、公開リポジトリへ含めません。次は売上CSV集計の1案件で実際の入力書式と検収条件を固める段階です。
