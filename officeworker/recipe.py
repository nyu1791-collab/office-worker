"""n8n風の「レシピ」: YAML にステップを並べるだけで業務フローになる。
各ステップは現在の表(df)を受け取って次へ渡す。案件ごとに YAML を1枚書けば納品物になる。"""
import glob
import os
import re
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
    opts = a if isinstance(a, dict) else {}
    new = io.read_many([fmt(f, ctx) for f in ([files] if isinstance(files, str) else files)], opts.get("source", True),
                       reader=_file_reader(opts), skip_duplicates=opts.get("skip_duplicate_files", False))
    if new.attrs.get("skipped_duplicates"):
        ctx.setdefault("skipped_duplicates", []).extend(new.attrs["skipped_duplicates"])
    if df is None or (isinstance(a, dict) and not a.get("append")):
        return new
    result = pd.concat([df, new], ignore_index=True)
    result.attrs["failed_files"] = df.attrs.get("failed_files", []) + new.attrs.get("failed_files", [])
    result.attrs["source_files"] = df.attrs.get("source_files", []) + new.attrs.get("source_files", [])
    return result


def _norm_col(c):
    return unicodedata.normalize("NFKC", str(c)).strip().replace(" ", "")


def _file_reader(opts):
    """ファイル単位の前処理。店ごとに列名が違っても（売上日/日付 など）統合前にそろえる。
    必須列が無いファイルは「読込失敗」として入力に残す（他のファイルは処理を続ける）。"""
    rename, require, normalize = opts.get("rename"), opts.get("require"), opts.get("normalize_columns")
    labels = opts.get("labels") or {}
    if not (rename or require or normalize or opts.get("as_text")):
        return None
    mapping = {_norm_col(k) if normalize else k: v for k, v in (rename or {}).items()}

    as_text = opts.get("as_text")

    def reader(path):
        # as_text: 全列を文字のまま読む（店舗/商品コードの先頭ゼロを保つ。数値・日付は to_number/to_date で変換）
        df = io.read_any(path, dtype=str) if as_text else io.read_any(path)
        if normalize:
            df.columns = [_norm_col(c) for c in df.columns]
        df = df.rename(columns=mapping)
        if df.columns.duplicated().any():
            dup = sorted(set(df.columns[df.columns.duplicated()]))
            raise ValueError(f"同じ意味の列が複数あります: {dup}（どちらを使うか rename で指定）")
        missing = [c for c in (require or []) if c not in df.columns]
        if missing:
            need = "・".join(labels.get(c, c) for c in missing)
            raise ValueError(f"必須の列（{need}）が見つかりません。このファイルの列: {', '.join(map(str, df.columns))}")
        return df[[c for c in df.columns if not str(c).startswith("Unnamed")]]
    return reader


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


# NFKC でも "-" にならないマイナス記号（数学のマイナス U+2212、各種ダッシュ）
MINUS = str.maketrans({"\u2212": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-", "\ufe63": "-"})


@step("to_number")
def _num(df, a, ctx):
    for c in a:
        # 空欄(NaN)は astype(str) でも NaN のままの pandas があるので明示的に空文字へ
        normalized = df[c].map(lambda v: "" if pd.isna(v) else unicodedata.normalize("NFKC", str(v)).strip().translate(MINUS))
        # 会計の慣習: ▲300 / △300 / (300) はマイナス
        normalized = normalized.str.replace(r"^[▲△]\s*", "-", regex=True).str.replace(r"^\((.*)\)$", r"-\1", regex=True)
        df[c] = pd.to_numeric(normalized.str.replace(r"[^\d.\-]", "", regex=True), errors="coerce")
    return df


@step("to_date")
def _date(df, a, ctx):
    for c in a:
        df[c] = df[c].map(_parse_date)
    return df


def _parse_date(v):
    """2026/10/1, 2026-10-01, 2026年10月1日, 令和8年10月1日, R8.10.1, 20261001, Excelの日付 → 2026-10-01。読めなければ空"""
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return None
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    s = unicodedata.normalize("NFKC", str(v)).strip()
    if not s:
        return None
    m = re.match(r"^(?:令和|R)\s*(\d+|元)\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})", s)
    if m:
        y = 2018 + (1 if m.group(1) == "元" else int(m.group(1)))
        s = f"{y}-{m.group(2)}-{m.group(3)}"
    else:
        s = re.sub(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", r"\1-\2-\3", s)
        if re.fullmatch(r"\d{8}", s):
            s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    # 年が4桁で先頭に無い日付（26/10/01、10/1 など）は推測しない。「2001-10-26」や「今年」に化けるため要確認へ
    if not re.match(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:$|[ T])", s):
        return None
    d = pd.to_datetime(s, errors="coerce", format="mixed")
    return None if pd.isna(d) else d.strftime("%Y-%m-%d")


@step("groupby")
def _group(df, a, ctx):
    """agg: {amount: sum}  または名前付き {売上合計: [amount, sum], 件数: [amount, count]}"""
    agg = a["agg"]
    if all(isinstance(v, (list, tuple)) and len(v) == 2 for v in agg.values()):
        return df.groupby(a["by"], as_index=False).agg(**{k: tuple(v) for k, v in agg.items()})
    return df.groupby(a["by"], as_index=False).agg(agg)


@step("pivot")  # {index: date, columns: store, values: amount, total: 合計}
def _pivot(df, a, ctx):
    total = a.get("total")
    out = df.pivot_table(index=a["index"], columns=a["columns"], values=a["values"], aggfunc=a.get("aggfunc", "sum"),
                         fill_value=0, margins=bool(total), margins_name=total or "All")
    out.columns = [str(c) for c in out.columns]
    return out.reset_index()


@step("keep")  # 現在の表に名前を付けて取っておく（分岐して別集計するため）
def _keep(df, a, ctx):
    ctx.setdefault("frames", {})[a] = df.copy()
    return df


@step("use")  # keep した表に戻る
def _use(df, a, ctx):
    return ctx["frames"][a].copy()


@step("quarantine")  # 必須項目が空/読めない行を分け、正常行だけ先へ流す。分けた行は keep 名（既定: 要確認）で use できる
def _quarantine(df, a, ctx):
    cols = a["columns"]
    empty = df[cols].map(lambda v: pd.isna(v) or str(v).strip() in ("", "nan", "None", "NaT"))
    bad_mask = empty.any(axis=1)
    bad, good = df[bad_mask].copy(), df[~bad_mask].copy()
    labels = a.get("labels") or {}
    bad.insert(0, "理由", [("未入力/読み取れない: " + "・".join(labels.get(c, c) for c in cols if row[c]))
                           for _, row in empty[bad_mask].iterrows()])
    ctx["vars"]["invalid_rows"] = len(bad)
    ctx.setdefault("frames", {})[a.get("keep", "要確認")] = bad
    if a.get("path"):
        io.write_any(bad, fmt(a["path"], ctx), sheet=a.get("sheet", "要確認"))
    if len(bad):
        print(f"  要確認 {len(bad)}行（{a.get('sheet', '要確認')}シート）")
    good.attrs.update(df.attrs)
    return good


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
    if isinstance(a, dict) and a.get("new") and Path(path).exists():
        Path(path).unlink()  # 前回の古いシートを残さない（入力から毎回作り直す）
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
