"""使い方: python -m officeworker <command>
  run recipes/x.yaml              レシピ実行（業務フロー本体）
  watch in/ recipes/x.yaml        フォルダ監視→新ファイルで自動実行
  merge "in/*.csv" -o out.xlsx    複数CSV/Excelを1つに統合
  invoice "in/*.pdf" -o out.xlsx  請求書PDF→一覧表
  pdf file.pdf -o out.csv         PDFの表を抽出
  tosheet file.csv --tab 名前     スプレッドシートへ反映
  notify "本文"                   Slack/Discord/Chatwork/メールへ通知
  new 案件名                      受託案件フォルダを雛形から作成
  build script.py                 exe化（依頼主PCにPython不要）"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(prog="officeworker", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("run"); p.add_argument("recipe"); p.add_argument("--var", nargs="*", default=[], help="key=value")
    p = sp.add_parser("watch"); p.add_argument("folder"); p.add_argument("recipe"); p.add_argument("--interval", type=int, default=30)
    for n in ("merge", "invoice", "pdf"):
        p = sp.add_parser(n); p.add_argument("src"); p.add_argument("-o", "--out", default=f"out/{n}.xlsx")
    p = sp.add_parser("tosheet"); p.add_argument("src"); p.add_argument("--tab", default="Sheet1"); p.add_argument("--append", action="store_true")
    p = sp.add_parser("notify"); p.add_argument("text"); p.add_argument("--attach")
    p = sp.add_parser("new"); p.add_argument("name")
    p = sp.add_parser("build"); p.add_argument("script"); p.add_argument("--name"); p.add_argument("--console", action="store_true")
    a = ap.parse_args()

    from . import io
    if a.cmd == "run":
        from . import recipe
        recipe.run(a.recipe, dict(kv.split("=", 1) for kv in a.var))
    elif a.cmd == "watch":
        from . import recipe
        folder, seen = Path(a.folder), set()
        print(f"監視中: {folder}（Ctrl+Cで終了）")
        while True:
            files = {p for p in folder.glob("*") if p.is_file()}
            if files - seen:
                try:
                    recipe.run(a.recipe)
                except Exception as e:
                    print(f"エラー: {e}")
                files = {p for p in folder.glob("*") if p.is_file()}  # move で退避した分を反映
            seen = files
            time.sleep(a.interval)
    elif a.cmd == "merge":
        df = io.read_many(a.src); io.write_any(df, a.out); print(f"{len(df)}行 → {a.out}")
    elif a.cmd == "invoice":
        from . import pdf
        df = pdf.invoices(a.src); io.write_any(df, a.out); print(df.to_string()); print(f"→ {a.out}")
    elif a.cmd == "pdf":
        from . import pdf
        df = pdf.tables(a.src); io.write_any(df, a.out); print(f"{len(df)}行 → {a.out}")
    elif a.cmd == "tosheet":
        from . import sheets
        print(sheets.push(io.read_any(a.src), a.tab, mode="append" if a.append else "replace"))
    elif a.cmd == "notify":
        from . import notify
        notify.send(a.text, a.attach)
    elif a.cmd == "new":
        dst = ROOT / "jobs" / a.name
        shutil.copytree(ROOT / "templates" / "client_job", dst)
        for d in ("in", "out"):
            (dst / d).mkdir(exist_ok=True)
        print(f"作成: {dst}\n次: spec.md に依頼内容を貼る → そのフォルダで claude を起動し「spec.mdを実装して」")
    elif a.cmd == "build":
        cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--clean", "--distpath", "dist", a.script]
        if a.name:
            cmd += ["--name", a.name]
        if not a.console:
            cmd += ["--noconsole"] if a.script.endswith("gui.py") else []
        subprocess.run(cmd, check=True)
        print("→ dist/ に exe ができました")


if __name__ == "__main__":
    main()
