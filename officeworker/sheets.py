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


def push(df: pd.DataFrame, tab="Sheet1", sheet_id=None, mode="replace"):
    ws = _ws(_sheet(sheet_id), tab, len(df.columns))
    data = df.astype(object).where(pd.notna(df), "").values.tolist()
    if mode == "append" and ws.get_all_values():
        ws.append_rows(data, value_input_option="USER_ENTERED")
    else:
        ws.clear()
        ws.update([list(map(str, df.columns))] + data, "A1", value_input_option="USER_ENTERED")
    return ws.url


def pull(tab="Sheet1", sheet_id=None) -> pd.DataFrame:
    return pd.DataFrame(_ws(_sheet(sheet_id), tab).get_all_records())
