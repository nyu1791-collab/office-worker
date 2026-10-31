"""売上CSV集計ツール（納品用エントリ）。ダブルクリック実行 / exe 化を想定。
使い方: in フォルダに CSV/Excel を入れて実行 → out/売上集計_YYYYMMDD.xlsx
開発時: python products/sales-csv-to-excel/run.py --sample   （同梱サンプルで動作確認）"""
import argparse
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
BASE = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent
if not FROZEN:
    sys.path.insert(0, str(BASE.parents[1]))  # リポジトリ直下（officeworker パッケージ）


def main():
    ap = argparse.ArgumentParser(description="売上CSV集計")
    ap.add_argument("--sample", action="store_true", help="同梱サンプル(sample/in)で実行し sample/out に出力")
    ap.add_argument("--input", default=None)
    ap.add_argument("--output", default=None)
    a = ap.parse_args()
    from officeworker import recipe

    indir = a.input or ("sample/in" if a.sample else "in")
    outdir = a.output or ("sample/out" if a.sample else "out")
    os.chdir(BASE)
    Path(indir).mkdir(parents=True, exist_ok=True)
    Path(outdir).mkdir(parents=True, exist_ok=True)
    recipe_path = BASE / "recipe.yaml"
    if FROZEN and not recipe_path.exists():  # exe 内同梱の既定レシピ
        recipe_path = Path(sys._MEIPASS) / "recipe.yaml"
    df, ctx = recipe.run_full(recipe_path, {"indir": indir, "outdir": outdir})
    print("\n==== 結果 ====")
    print(f"出力: {ctx['vars'].get('file')}")
    print(f"要確認の行: {ctx['vars'].get('invalid_rows', 0)}件（『要確認』シート）")
    for f in ctx.get("skipped_duplicates", []):
        print(f"二重投入として除外: {Path(f).name}")
    for f in ctx.get("failed_files", []):
        print(f"読めなかったファイル（入力に残しています）: {Path(f['file']).name} … {f['error']}")
    return ctx


if __name__ == "__main__":
    code = 0
    try:
        main()
    except PermissionError as e:
        print(f"\n保存できませんでした: {e.filename or e}\n"
              "out フォルダの集計Excelを開いたままになっていませんか？ Excel を閉じてからもう一度実行してください。")
        code = 1
    except FileNotFoundError as e:
        print(f"\n{e}\nin フォルダに売上の CSV / Excel を入れてから実行してください。")
        code = 1
    except Exception as e:
        print(f"\nエラー: {e}\nこの画面を撮影してご連絡ください。")
        code = 1
    if FROZEN:
        input("\nEnter で閉じます")
    sys.exit(code)
