"""PDF → 表 / テキスト / 請求書の項目抽出。
請求書は Gemini で構造化（キー無しなら正規表現でベストエフォート）。"""
import re
import unicodedata
from pathlib import Path

import pandas as pd
import pdfplumber

from . import llm

INVOICE_FIELDS = ["file", "issuer", "invoice_no", "issue_date", "due_date", "subtotal", "tax", "total", "registration_no", "bank"]


def text(path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def tables(path) -> pd.DataFrame:
    rows, header = [], None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for t in page.extract_tables():
                if not t:
                    continue
                if header is None:
                    header = [str(h or f"col{i}") for i, h in enumerate(t[0])]
                    t = t[1:]
                rows += [r for r in t if r != header]
    if header is None:
        return pd.DataFrame()
    w = len(header)
    return pd.DataFrame([(r + [None] * w)[:w] for r in rows], columns=header)


def _num(s):
    s = str("" if s is None else s).replace("，", ",").replace("．", ".")
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    m = re.search(r"-?[\d,]+(?:\.\d+)?", s)
    if not m:
        return ""
    v = float(m.group(0).replace(",", ""))
    return int(v) if v.is_integer() else v


def invoice(path) -> dict:
    t = text(path)
    if not t.strip():
        raise ValueError("PDFから文字を読み取れません。画像だけのPDFはOCR未対応のため、文字を選択できるPDFを用意してください")
    prompt = (
        "次の請求書テキストから項目を抽出し JSON で返してください。金額は数値(円)、日付は YYYY-MM-DD、無い項目は空文字。\n"
        'キー: issuer(発行元), invoice_no, issue_date, due_date, subtotal, tax, total, registration_no(インボイス登録番号T+13桁), bank(振込先)\n\n'
        + t[:12000]
    )
    res = None
    try:
        res = llm.ask(prompt, json_mode=True, temperature=0)
    except Exception as e:
        print(f"  LLM失敗→正規表現: {e}")
    if not res:
        normalized = unicodedata.normalize("NFKC", t)
        g = lambda pat: (re.search(pat, normalized) or [None, ""])[1]
        res = {
            "issuer": t.strip().splitlines()[0] if t.strip() else "",
            "invoice_no": g(r"(?:請求書番号|請求番号|No\.?)\s*[:：]?\s*([\w-]+)"),
            "issue_date": g(r"(?:請求日|発行日)\s*[:：]?\s*([\d/年月日.-]+)"),
            "due_date": g(r"(?:支払期限|お支払期限|振込期限)\s*[:：]?\s*([\d/年月日.-]+)"),
            "subtotal": _num(g(r"小計\s*[:：]?\s*[¥￥]?\s*([+-]?[\d,]+(?:\.\d+)?)")),
            "tax": _num(g(r"消費税(?:額)?(?:\s*\(?\d+%\)?)?\s*[:：]?\s*[¥￥]?\s*([+-]?[\d,]+(?:\.\d+)?)")),
            "total": _num(g(r"(?:合計|ご請求金額|請求金額|総額)(?:\(税込\))?\s*[:：]?\s*[¥￥]?\s*([+-]?[\d,]+(?:\.\d+)?)")),
            "registration_no": g(r"(T\d{13})"),
            "bank": g(r"((?:\S+銀行)\s*\S*支店[^\n]*)"),
        }
    res["file"] = Path(path).name
    for k in ("issue_date", "due_date"):
        res[k] = _date(res.get(k))
    for k in ("subtotal", "tax", "total"):
        res[k] = _num(res.get(k))
    if res["total"] == "":
        raise ValueError("請求合計金額を読み取れません。原本と書式を確認してください")
    return {k: res.get(k, "") for k in INVOICE_FIELDS}


def _date(s):
    """2026年10月1日 / 2026/10/1 / R8.10.1 / 令和8年10月1日 → 2026-10-01"""
    s = str(s or "").strip()
    if not s:
        return ""
    m = re.search(r"(?:令和|R)\s*(\d+|元)\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})", s)
    if m:
        y = 2018 + (1 if m.group(1) == "元" else int(m.group(1)))
        return f"{y:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{4})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})", s)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else s


def invoices(pattern) -> pd.DataFrame:
    import glob
    from .io import read_files
    return read_files(sorted(glob.glob(pattern, recursive=True)),
                      reader=lambda f: pd.DataFrame([invoice(f)], columns=INVOICE_FIELDS),
                      add_source=False, columns=INVOICE_FIELDS)
