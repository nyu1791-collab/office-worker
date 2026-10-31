"""HTTP API。n8n（docker/n8n）や GAS、他ツールから officeworker を呼ぶための窓口。
起動: python -m officeworker serve  → http://localhost:8765/docs で試せる"""
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from pydantic import BaseModel

from . import io, llm, notify, pdf, recipe

ROOT = Path(os.getenv("OW_ROOT", ".")).resolve()
app = FastAPI(title="office-worker API")
_lock = threading.Lock()  # レシピは cwd を切り替えるので同時実行させない


def _auth(token):
    want = os.getenv("OW_API_TOKEN")
    if want and token != want:
        raise HTTPException(401, "bad token")


def _records(df: pd.DataFrame, limit=500):
    return df.head(limit).astype(object).where(pd.notna(df.head(limit)), None).to_dict("records")


def _save_uploads(files: list[UploadFile], sub="in/api") -> list[Path]:
    d = ROOT / sub / uuid4().hex
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for index, f in enumerate(files):
        name = Path((f.filename or "upload.bin").replace("\\", "/")).name
        if name in ("", ".", ".."):
            name = "upload.bin"
        p = d / str(index) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as w:
            shutil.copyfileobj(f.file, w)
        out.append(p)
    return out


def _batch_read(paths, **kwargs):
    if not paths:
        raise HTTPException(400, "no supported input files")
    try:
        return io.read_files(paths, error_log=ROOT / "error.log", **kwargs)
    except io.BatchReadError as exc:
        raise HTTPException(422, {"message": str(exc), "failed_files": exc.failures}) from exc


def _after(df, sheet, notify_text, file_out):
    res = {"rows": len(df), "data": _records(df), "failed_files": df.attrs.get("failed_files", [])}
    if file_out:
        destination = (ROOT / file_out).resolve()
        if not destination.is_relative_to(ROOT.resolve()):
            raise HTTPException(400, "output path must be inside OW_ROOT")
        # APIの結果は依頼ごとに保管する。同日・同名の出力も過去の結果を上書きしない。
        destination = destination.with_name(f"{destination.stem}_{uuid4().hex}{destination.suffix}")
        with _lock:
            res["file"] = str(io.write_any(df, destination))
    if sheet:
        from . import sheets
        res["sheet_url"] = sheets.push(df, sheet, mode="append")
    if notify_text:
        notify.send(notify_text.format(rows=len(df), file=res.get("file", "")), attach=res.get("file"))
    return res


@app.get("/health")
def health():
    return {"ok": True, "recipes": sorted(p.stem for p in (ROOT / "recipes").glob("*.yaml"))}


class RunReq(BaseModel):
    vars: dict = {}


@app.post("/run/{name}")
def run_recipe(name: str, req: RunReq | None = None, x_token: str | None = Header(None)):
    _auth(x_token)
    path = ROOT / "recipes" / f"{name}.yaml"
    if not path.exists():
        raise HTTPException(404, f"recipe not found: {name}")
    with _lock:
        cwd = os.getcwd()
        os.chdir(ROOT)  # レシピ内の相対パスをリポジトリ基準に
        try:
            df, ctx = recipe.run_full(path, (req.vars if req else {}))
        finally:
            os.chdir(cwd)
    return {"rows": 0 if df is None else len(df), "vars": {k: str(v) for k, v in ctx["vars"].items()}, "failed_files": ctx["failed_files"],
            "data": [] if df is None else _records(df, 100)}


@app.post("/invoice")
def invoice(file: list[UploadFile] = File(...), sheet: str = "", notify_text: str = "",
            out: str = "out/請求書_{date}.xlsx", x_token: str | None = Header(None)):
    """請求書PDF（複数可）→ 項目抽出。?sheet=タブ名 でシート追記、?notify_text=... で通知"""
    _auth(x_token)
    paths = _save_uploads(file)
    df = _batch_read([p for p in paths if p.suffix.lower() == ".pdf"],
                     reader=lambda p: pd.DataFrame([pdf.invoice(p)], columns=pdf.INVOICE_FIELDS),
                     add_source=False, columns=pdf.INVOICE_FIELDS)
    return _after(df, sheet, notify_text, out.format(date=datetime.now().strftime("%Y%m%d")) if out else "")


@app.post("/merge")
def merge(file: list[UploadFile] = File(...), sheet: str = "", notify_text: str = "",
          out: str = "out/統合_{date}.xlsx", x_token: str | None = Header(None)):
    """CSV/Excel（文字コード混在OK）を統合"""
    _auth(x_token)
    df = _batch_read(_save_uploads(file))
    return _after(df, sheet, notify_text, out.format(date=datetime.now().strftime("%Y%m%d")) if out else "")


@app.post("/pdf-tables")
def pdf_tables(file: list[UploadFile] = File(...), x_token: str | None = Header(None)):
    _auth(x_token)
    df = _batch_read(_save_uploads(file), reader=pdf.tables)
    return {"rows": len(df), "data": _records(df), "failed_files": df.attrs.get("failed_files", [])}


class AiReq(BaseModel):
    instruction: str = "要約して"
    text: str = ""
    json_mode: bool = False


@app.post("/ai")
def ai(req: AiReq, x_token: str | None = Header(None)):
    """分類・要約・抽出など。n8n の Webhook → ここ → 結果を返す"""
    _auth(x_token)
    res = llm.ask(f"{req.instruction}\n\n{req.text}", json_mode=req.json_mode, temperature=0)
    if res is None:
        raise HTTPException(400, "GEMINI_API_KEY 未設定")
    return {"result": res}


class NotifyReq(BaseModel):
    text: str
    subject: str = "【自動通知】"


@app.post("/notify")
def notify_(req: NotifyReq, x_token: str | None = Header(None)):
    _auth(x_token)
    return {"sent": notify.send(req.text, subject=req.subject)}


def serve(host="0.0.0.0", port=8765):
    import uvicorn
    uvicorn.run(app, host=host, port=port)
