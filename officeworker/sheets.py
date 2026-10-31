"""Googleスプレッドシート読み書き（サービスアカウント）。"""
import os

import pandas as pd


def _sheet(sheet_id=None):
    import gspread
    cred = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
    return gspread.service_account(filename=cred).open_by_key(sheet_id or os.environ["GOOGLE_SHEET_ID"])


def _ws(sh, name, cols=26):
    import gspread
    try:
        return sh.worksheet(name)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(name, rows=1000, cols=cols)


def _cell(v):
    """シートへ送れる値に。日付は文字列、欠損は空、= / @ で始まる文字は式として実行させない。"""
    if v is None or (not isinstance(v, (list, dict)) and pd.isna(v)):
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d %H:%M:%S").removesuffix(" 00:00:00")
    if hasattr(v, "item"):  # numpy の数値型
        v = v.item()
    if isinstance(v, str) and v[:1] in ("=", "@"):
        return "'" + v
    return v


def rows_of(df: pd.DataFrame):
    return [[_cell(v) for v in row] for row in df.itertuples(index=False, name=None)]


def push(df: pd.DataFrame, tab="Sheet1", sheet_id=None, mode="replace"):
    ws = _ws(_sheet(sheet_id), tab, len(df.columns))
    data = rows_of(df)
    existing = ws.get_all_values()
    if mode == "append" and existing:
        ws.append_rows(data, value_input_option="USER_ENTERED")
        return ws.url
    # 先に clear すると通信失敗時にシートが空になる。末尾の古い行も空白で上書きして1回で置き換える
    grid = [list(map(str, df.columns))] + data
    width = max([len(df.columns), *(len(r) for r in existing)] or [1])
    grid = [r + [""] * (width - len(r)) for r in grid]
    grid += [[""] * width for _ in range(max(0, len(existing) - len(grid)))]
    if len(grid) > ws.row_count or width > ws.col_count:
        ws.resize(rows=max(len(grid), ws.row_count), cols=max(width, ws.col_count))
    ws.update(grid, "A1", value_input_option="USER_ENTERED")
    return ws.url


def pull(tab="Sheet1", sheet_id=None) -> pd.DataFrame:
    return pd.DataFrame(_ws(_sheet(sheet_id), tab).get_all_records())
