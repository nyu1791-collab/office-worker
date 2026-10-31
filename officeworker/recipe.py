"""n8n風の「レシピ」: YAML にステップを並べるだけで業務フローになる。
各ステップは現在の表(df)を受け取って次へ渡す。案件ごとに YAML を1枚書けば納品物になる。"""
import glob
import os
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from . import io, llm, notify, pdf

STEPS = {}


def step(name):
    def deco(fn):
        STEPS[name] = fn
        return fn
    return deco


def fmt(s, ctx):
    now = datetime.now()
    return str(s).format(date=now.strftime("%Y%m%d"), datetime=now.strftime("%Y%m%d_%H%M"), month=now.strftime("%Y%m"),
                         rows=len(ctx["df"]) if ctx["df"] is not None else 0, **ctx["vars"])


@step("load")
def _load(df, a, ctx):
    if isinstance(a, dict) and "sheet" in a:
        from . import sheets
        return sheets.pull(a["sheet"], a.get("id"))
    files = a["files"] if isinstance(a, dict) else a
    new = io.read_many([fmt(f, ctx) for f in ([files] if isinstance(files, str) else files)], a.get("source", True) if isinstance(a, dict) else True)
    if df is None or (isinstance(a, dict) and not a.get("append")):
        return new
    result = pd.concat([df, new], ignore_index=True)
    result.attrs["failed_files"] = df.attrs.get("failed_files", []) + new.attrs.get("failed_files", [])
    result.attrs["source_files"] = df.attrs.get("source_files", []) + new.attrs.get("source_files", [])
    return result


@step("invoices")
def _inv(df, a, ctx):
    return pdf.invoices(fmt(a["files"] if isinstance(a, dict) else a, ctx))


@step("pdf_tables")
def _pt(df, a, ctx):
    return io.read_files(sorted(glob.glob(fmt(a, ctx))), reader=pdf.tables)


@step("rename")
def _rename(df, a, ctx):
    return df.rename(columns=a)


@step("select")
def _select(df, a, ctx):
    return df[[c for c in a if c in df.columns]]


@step("filter")
def _filter(df, a, ctx):
    return df.query(a, engine="python")


@step("dedupe")
def _dedupe(df, a, ctx):
    return df.drop_duplicates(subset=a or None, keep="last")


@step("sort")
def _sort(df, a, ctx):
    by = a["by"] if isinstance(a, dict) else a
    return df.sort_values(by, ascending=not (isinstance(a, dict) and a.get("desc")))


@step("derive")  # {新列: "式"}  例) 税込: "金額 * 1.1"
def _derive(df, a, ctx):
    for col, expr in a.items():
        df[col] = df.eval(expr, engine="python")
    return df


@step("to_number")
def _num(df, a, ctx):
    for c in a:
        normalized = df[c].astype(str).map(lambda value: unicodedata.normalize("NFKC", value))
        df[c] = pd.to_numeric(normalized.str.replace(r"[^\d.\-]", "", regex=True), errors="coerce")
    return df


@step("to_date")
def _date(df, a, ctx):
    for c in a:
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


@step("groupby")
def _group(df, a, ctx):
    return df.groupby(a["by"], as_index=False).agg(a["agg"])


@step("join")
def _join(df, a, ctx):
    other = io.read_any(fmt(a["file"], ctx))
    return df.merge(other, on=a["on"], how=a.get("how", "left"))


@step("ai")  # 1行ずつ AI 処理（分類・要約・抽出など）
def _ai(df, a, ctx):
    out = []
    for _, r in df.iterrows():
        res = llm.ask(a["prompt"].format(**r.to_dict()), temperature=0)
        out.append(res or "")
    df[a.get("to", "ai")] = out
    return df


@step("save")
def _save(df, a, ctx):
    path = fmt(a["path"] if isinstance(a, dict) else a, ctx)
    io.write_any(df, path, sheet=a.get("sheet", "Sheet1") if isinstance(a, dict) else "Sheet1")
    ctx["vars"]["file"] = path
    print(f"  保存: {path} ({len(df)}行)")
    return df


@step("sheet")
def _sheet(df, a, ctx):
    from . import sheets
    url = sheets.push(df, a.get("tab", "Sheet1"), a.get("id"), a.get("mode", "replace"))
    ctx["vars"]["sheet_url"] = url
    print(f"  シート更新: {url}")
    return df


@step("notify")
def _notify(df, a, ctx):
    text = a["text"] if isinstance(a, dict) else a
    notify.send(fmt(text, ctx), attach=ctx["vars"].get("file") if isinstance(a, dict) and a.get("attach") else None)
    return df


@step("move")  # 処理済みファイルを退避
def _move(df, a, ctx):
    dest = Path(fmt(a["to"], ctx)); dest.mkdir(parents=True, exist_ok=True)
    failed = {failure["file"] for failure in ctx.get("failed_files", [])}
    loaded = set(ctx.get("source_files", []))
    for f in glob.glob(fmt(a["files"], ctx), recursive=True):
        resolved = str(Path(f).resolve())
        if resolved in failed or resolved not in loaded:
            print(f"  退避しません（読込未完了）: {f}")
            continue
        _archive(Path(f), dest)
    return df


def _archive(source, dest):
    """既存の退避ファイルを上書きせず、コピーが完了してから入力を削除する。"""
    index = 1
    while True:
        name = source.name if index == 1 else f"{source.stem}-{index}{source.suffix}"
        target = dest / name
        try:
            writer = target.open("xb")
            break
        except FileExistsError:
            index += 1
    try:
        with writer, source.open("rb") as reader:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        shutil.copystat(source, target)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    source.unlink()
    return target


@step("print")
def _print(df, a, ctx):
    print(df.head(a if isinstance(a, int) else 20).to_string())
    return df


def run(path, vars=None):
    return run_full(path, vars)[0]


def run_full(path, vars=None):
    """-> (df, ctx)。ctx["vars"] に file / sheet_url など各ステップの出力が入る"""
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    ctx = {"df": None, "vars": {**spec.get("vars", {}), **(vars or {})}, "failed_files": [], "source_files": []}
    print(f"▶ {spec.get('name', path)}")
    for i, s in enumerate(spec["steps"], 1):
        (name, arg), = s.items() if isinstance(s, dict) else ((s, None),)
        print(f" {i}. {name}")
        ctx["df"] = STEPS[name](ctx["df"], arg, ctx)
        if ctx["df"] is not None:
            for source in ctx["df"].attrs.get("source_files", []):
                if source not in ctx["source_files"]:
                    ctx["source_files"].append(source)
            for failure in ctx["df"].attrs.get("failed_files", []):
                if failure not in ctx["failed_files"]:
                    ctx["failed_files"].append(failure)
    return ctx["df"], ctx
