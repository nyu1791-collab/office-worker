"""投稿先アダプタ。method ごとに post(...) -> 結果の説明文 を返す。
  email   : 媒体の「写メ日記メール投稿」アドレスへ写真付きメール（最も壊れにくい。多くのポータルが公式に提供）
  x       : X API（写真付き）
  browser : browser-use の AI が媒体の管理画面で投稿（メール投稿が無い媒体用。要 requirements-browser）
  folder  : 手動投稿用に「タイトル・本文・写真」をフォルダへ書き出す（既定・安全）"""
import os
import smtplib
from email.header import Header
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path


class Uncertain(RuntimeError):
    """送信を試みたが相手に届いたか確定できない（自動で再送しない）"""


def post(method, name, pcfg, cast, text, photo, job_id):
    fn = {"email": _email, "x": _x, "browser": _browser, "folder": _folder}.get(method)
    if not fn:
        raise ValueError(f"不明な method: {method}")
    return fn(name, pcfg, cast, text, photo, job_id)


def _email(name, pcfg, cast, text, photo, job_id):
    to = pcfg.get("email")
    if not to:
        raise ValueError(f"{name}: casts.yaml にこのキャストの投稿用メールアドレス（portals.{name}.email）がありません")
    user = pcfg.get("smtp_user") or os.environ["SMTP_USER"]
    pw = pcfg.get("smtp_password") or os.environ["SMTP_PASSWORD"]
    sender = pcfg.get("from") or cast.get("mail_from") or user  # 媒体側に登録した送信元と一致させる
    msg = MIMEMultipart()
    msg["Subject"] = str(Header(text["title"], "utf-8"))
    msg["From"], msg["To"] = formataddr((str(Header(cast.get("name", ""), "utf-8")), sender)), to
    msg.attach(MIMEText(text["body"], "plain", "utf-8"))
    if photo and Path(photo).exists():
        img = MIMEImage(Path(photo).read_bytes(), _subtype="jpeg")
        img.add_header("Content-Disposition", "attachment", filename="photo.jpg")
        msg.attach(img)
    host, port = os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "465"))
    try:
        s = smtplib.SMTP_SSL(host, port, timeout=30)
        s.login(user, pw)
    except Exception as e:  # 接続・認証の失敗はまだ送っていない
        raise RuntimeError(f"SMTP 接続/認証失敗: {e}") from e
    try:
        refused = s.send_message(msg, from_addr=sender)
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as e:
        raise RuntimeError(f"送信拒否: {e}") from e
    except Exception as e:
        raise Uncertain(f"送信結果が不明（媒体側で投稿の有無を確認）: {e}") from e
    finally:
        try:
            s.quit()
        except Exception:
            pass
    if refused:
        raise RuntimeError(f"宛先拒否: {refused}")
    return f"mail→{to}"


def _x(name, pcfg, cast, text, photo, job_id):
    import tweepy
    keys = {k: pcfg.get(k.lower()) or os.environ[k] for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")}
    body = (pcfg.get("prefix", "") + text["body"])[: pcfg.get("max_chars", 140)]
    media_ids = None
    if photo and Path(photo).exists():
        auth = tweepy.OAuth1UserHandler(keys["X_API_KEY"], keys["X_API_SECRET"], keys["X_ACCESS_TOKEN"], keys["X_ACCESS_SECRET"])
        media_ids = [tweepy.API(auth).media_upload(photo).media_id]
    c = tweepy.Client(consumer_key=keys["X_API_KEY"], consumer_secret=keys["X_API_SECRET"],
                      access_token=keys["X_ACCESS_TOKEN"], access_token_secret=keys["X_ACCESS_SECRET"])
    try:
        r = c.create_tweet(text=body, media_ids=media_ids)
    except tweepy.HTTPException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if isinstance(status, int) and 400 <= status < 500 and status != 408:
            raise RuntimeError(f"X 拒否: {e}") from e
        raise Uncertain(f"X 投稿結果が不明: {e}") from e
    return f"https://x.com/i/status/{r.data['id']}"


def _browser(name, pcfg, cast, text, photo, job_id):
    """媒体ごとの手順は diary.yaml の portals.<name>.browser_task に日本語で書く（ログインは diary-login で一度だけ）"""
    import asyncio
    try:
        from browser_use import Agent, Browser, ChatGoogle
    except ImportError as e:
        raise RuntimeError("browser 投稿には pip install -r requirements-browser.txt が必要") from e
    from pydantic import BaseModel

    class Result(BaseModel):
        ok: bool
        note: str

    profile = Path(os.getenv("DIARY_DIR", "diary_data")) / "browser_profile" / name
    task = (pcfg.get("browser_task") or f"{pcfg.get('url', '')} の管理画面で写メ日記を新規作成し投稿する") + f"""
キャスト: {cast.get('name')}（管理画面でこのキャストを選ぶ）
タイトル: {text['title']}
本文:
{text['body']}
写真: {photo or 'なし'}（アップロード欄があれば添付）
投稿完了画面を確認できたら ok=true。ログイン画面・エラーなら ok=false で理由を note に。"""

    async def run():
        b = Browser(headless=pcfg.get("headless", True), user_data_dir=str(profile))
        try:
            agent = Agent(task=task, llm=ChatGoogle(model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), api_key=os.getenv("GEMINI_API_KEY")),
                          browser=b, output_model_schema=Result, available_file_paths=[photo] if photo else None)
            h = await agent.run(max_steps=int(pcfg.get("max_steps", 30)))
            return Result.model_validate_json(h.final_result()) if h.final_result() else Result(ok=False, note="結果なし")
        finally:
            await b.kill()

    try:
        res = asyncio.run(run())
    except Exception as e:
        raise Uncertain(f"ブラウザ投稿が途中で止まった（媒体側で確認）: {e}") from e
    if not res.ok:
        raise Uncertain(res.note or "完了を確認できず")
    return res.note or "browser ok"


def _folder(name, pcfg, cast, text, photo, job_id):
    import shutil
    d = Path(pcfg.get("dir") or Path(os.getenv("DIARY_DIR", "diary_data")) / "outbox") / name / f"{job_id}_{cast['id']}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "本文.txt").write_text(f"{text['title']}\n\n{text['body']}\n", encoding="utf-8")
    if photo and Path(photo).exists():
        shutil.copy(photo, d / "photo.jpg")
    return str(d)
