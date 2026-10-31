# 納品手順（自分用）

## 1. 受注〜作成
1. `python -m officeworker new 顧客名_売上集計` → `jobs/顧客名_売上集計/`
2. `products/sales-csv-to-excel/` の `recipe.yaml` `run.py` `MANUAL.md` をその案件フォルダにコピー
3. 顧客サンプルを `jobs/.../in/` に置き、SPEC.md のヒアリング項目を `spec.md` に記入
4. 見出しの違いは `recipe.yaml` の `rename` に追加 → `python run.py` で実行
5. ACCEPTANCE.md の B-4（店舗別合計が手集計と一致）を確認。不一致は明細と要確認で原因を説明

## 2. exe 作成（Windows）
```powershell
cd jobs\顧客名_売上集計        # または products\sales-csv-to-excel
..\..\.venv\Scripts\Activate.ps1
.\build.ps1                      # → dist\売上集計\ に exe 一式
```
`build.ps1` が無い案件フォルダでは `products\sales-csv-to-excel\build.ps1` をコピーして使う。

## 3. 出荷前チェック（自分の PC）
- [ ] `python -m unittest tests.test_product_sales` が OK（標準版のロジックを変えていないこと）
- [ ] `dist\売上集計\` で exe をダブルクリック → 顧客サンプルで `out` に Excel ができる
- [ ] Python が入っていない Windows（別PC や Windows サンドボックス）でも起動する
- [ ] 顧客の実データ・`error.log`・`out` の中身を zip に入れていない

## 4. 渡すもの（zip）
```
売上集計/
  売上集計.exe
  recipe.yaml      … 列名の設定（顧客は触らない）
  MANUAL.md → 説明書.pdf などに変換して同梱
  in/              … 空
  out/             … 空
```

## 5. 引き渡し後
- 顧客 PC で一緒に1回実行（ACCEPTANCE B-7, C-8）
- 再販用テンプレにする場合: 顧客名・店舗名・金額・固有の列名を取り除き、再販の許可を確認してから `products/` に反映
