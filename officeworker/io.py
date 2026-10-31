"""どんな表ファイルでも DataFrame に。日本の CSV（Shift_JIS / UTF-8 BOM）も自動判定。"""
from pathlib import Path
import glob

import pandas as pd

ENCODINGS = ("utf-8-sig", "cp932", "utf-8", "euc-jp")


def read_any(path, **kw) -> pd.DataFrame:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(p, sheet_name=kw.pop("sheet", 0), **kw)
    if ext == ".json":
        return pd.read_json(p, **kw)
    if ext == ".pdf":
        from .pdf import tables
        return tables(p)
    sep = "\t" if ext == ".tsv" else kw.pop("sep", ",")
    for enc in ENCODINGS:
        try:
            return pd.read_csv(p, encoding=enc, sep=sep, **kw)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"文字コード判定失敗: {p}")


def read_many(patterns, add_source=True) -> pd.DataFrame:
    if isinstance(patterns, str):
        patterns = [patterns]
    files = sorted({f for pat in patterns for f in glob.glob(pat, recursive=True)})
    if not files:
        raise FileNotFoundError(f"該当ファイルなし: {patterns}")
    dfs = []
    for f in files:
        df = read_any(f)
        if add_source:
            df["_source"] = Path(f).name
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


def write_any(df: pd.DataFrame, path, sheet="Sheet1"):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        mode = "a" if p.exists() else "w"
        with pd.ExcelWriter(p, engine="openpyxl", mode=mode, **({"if_sheet_exists": "replace"} if mode == "a" else {})) as w:
            df.to_excel(w, sheet_name=sheet, index=False)
        _autofit(p, sheet)
    elif ext == ".json":
        df.to_json(p, orient="records", force_ascii=False, indent=2)
    else:
        df.to_csv(p, index=False, encoding="utf-8-sig")  # Excelで文字化けしない
    return p


def _autofit(path, sheet):
    from openpyxl import load_workbook
    wb = load_workbook(path)
    ws = wb[sheet]
    for col in ws.columns:
        width = max((len(str(c.value)) if c.value is not None else 0) for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(8, width * 1.6), 60)
    ws.freeze_panes = "A2"
    wb.save(path)
