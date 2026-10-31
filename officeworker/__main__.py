"""使い方: python -m officeworker <command>
  run recipes/x.yaml              レシピ実行（業務フロー本体）
  watch in/ recipes/x.yaml        フォルダ監視→新ファイルで自動実行
  merge "in/*.csv" -o out.xlsx    複数CSV/Excelを1つに統合
  invoice "in/*.pdf" -o out.xlsx  請求書PDF→一覧表
  pdf file.pdf -o out.csv         PDFの表を抽出
  tosheet file.csv --tab 名前     スプレッドシートへ反映
  notify "本文"                   Slack/Discord/Chatwork/メールへ通知
  new 案件名                      受託案件フォルダを雛形から作成
  agent jobs/案件名 [--engine X]  spec.md を AI（OpenHands SDK / Claude Code / opencode）が自動実装
  build script.py                 exe化（依頼主PCにPython不要）
  serve [--port 8765]             HTTP API（n8n・GAS から呼ぶ）"""
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
    p = sp.add_parser("agent"); p.add_argument("job"); p.add_argument("--engine", choices=["openhands", "claude", "opencode"]); p.add_argument("--extra", default="")
    p = sp.add_parser("serve"); p.add_argument("--port", type=int, default=8765); p.add_argument("--host", default="127.0.0.1", help="既定はこのPCのみ。Linux の Docker から呼ぶ等で 0.0.0.0 にする場合は OW_API_TOKEN を設定")
    p = sp.add_parser("build"); p.add_argument("script"); p.add_argument("--name"); p.add_argument("--console", action="store_true")
    sp.add_parser("llm-check", help="Gemini 等の接続確認（用途ごとの接続先・検索の裏付け）")
    from .media import cli as media_cli
    media_cli.add_parsers(sp)
    from .manga import cli as manga_cli
    manga_cli.add_parsers(sp)
    from .diary import cli as diary_cli
    diary_cli.add_parsers(sp)
    a = ap.parse_args()
    if a.cmd.startswith("diary-"):
        try:
            return diary_cli.run(a)
        except PermissionError as e:
            raise SystemExit(str(e))
    if a.cmd == "llm-check":
        from . import llm
        return llm.check()
    if a.cmd in ("mosaic", "clips", "creator-job"):
        return media_cli.run(a)
    if a.cmd in ("manga-translate", "manga-render"):
        return manga_cli.run(a)

    from . import io
    if a.cmd == "run":
        from . import recipe
        recipe.run(a.recipe, dict(kv.split("=", 1) for kv in a.var))
    elif a.cmd == "watch":
        from . import recipe
        folder, seen, last = Path(a.folder), {}, None
        print(f"監視中: {folder}（Ctrl+Cで終了）")
        while True:
            snap = {p: (p.stat().st_size, p.stat().st_mtime) for p in folder.glob("*")
                    if p.is_file() and not p.name.startswith(("~$", ".~lock"))}
            new = {p for p in snap if seen.get(p) != snap[p]}
            # コピー途中のファイルを読まないよう、前回の確認から大きさ・更新時刻が変わっていない時だけ実行
            if new and snap == last:
                try:
                    recipe.run(a.recipe)
                except Exception as e:
                    print(f"エラー: {e}")
                snap = {p: (p.stat().st_size, p.stat().st_mtime) for p in folder.glob("*") if p.is_file()}
                seen = snap
            last = snap
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
        print(f"作成: {dst}\n次: spec.md に依頼内容を貼る → python -m officeworker agent jobs/{a.name}")
    elif a.cmd == "agent":
        from . import agent
        agent.run(a.job, a.engine, a.extra)
    elif a.cmd == "serve":
        from . import server
        server.serve(a.host, a.port)
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
