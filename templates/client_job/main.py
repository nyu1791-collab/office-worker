"""案件用スクリプト雛形。ダブルクリック実行を想定（exe化しても動くよう相対パスは実行ファイル基準）。"""
import sys
from pathlib import Path

BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
IN, OUT = BASE / "in", BASE / "out"


def main():
    import pandas as pd
    OUT.mkdir(exist_ok=True)
    files = sorted(IN.glob("*.csv")) + sorted(IN.glob("*.xlsx"))
    dfs = []
    for f in files:
        if f.suffix == ".csv":
            for enc in ("utf-8-sig", "cp932"):
                try:
                    dfs.append(pd.read_csv(f, encoding=enc)); break
                except UnicodeDecodeError:
                    pass
        else:
            dfs.append(pd.read_excel(f))
    if not dfs:
        print("in フォルダにファイルがありません"); return
    df = pd.concat(dfs, ignore_index=True)
    # ===== ここに案件固有の処理 =====

    out = OUT / "result.xlsx"
    df.to_excel(out, index=False)
    print(f"完了: {out} ({len(df)}行)")


if __name__ == "__main__":
    try:
        main()
    finally:
        if getattr(sys, "frozen", False):
            input("Enterで閉じます")
