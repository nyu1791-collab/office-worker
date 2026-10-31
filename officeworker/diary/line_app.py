"""LINE 公式アカウントの Webhook。キャストは「写真 → 一言メモ」を送るだけ。
  写真      → 受け取り、メモを待つ
  メモ      → 日記文を作ってプレビューを返信（approval: line のとき）／すぐ投稿（approval: none）
  OK        → 各媒体へ投稿（バックグラウンド）、結果を返信
  やり直し  → 文章だけ作り直す
  キャンセル → 破棄
未登録の人には LINE ユーザーID を返す（店舗が casts.yaml に書けば使える）。
起動: python -m officeworker diary-serve → cloudflared 等で https 公開 → LINE Developers の Webhook URL に /callback を設定"""
import json
import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from . import core

app = FastAPI(title="shop-diary LINE webhook")
OK_WORDS = {"ok", "ｏｋ", "OK", "はい", "投稿", "送信", "おけ"}
SENT = []  # テスト用（LINE_CHANNEL_ACCESS_TOKEN が無いときの返信先）


def _api():
    from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, MessagingApiBlob
    client = ApiClient(Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"]))
    return MessagingApi(client), MessagingApiBlob(client)


def reply(token, text, quick=()):
    if not os.getenv("LINE_CHANNEL_ACCESS_TOKEN"):
        SENT.append(text)
        return
    from linebot.v3.messaging import MessageAction, QuickReply, QuickReplyItem, ReplyMessageRequest, TextMessage
    qr = QuickReply(items=[QuickReplyItem(action=MessageAction(label=q, text=q)) for q in quick]) if quick else None
    _api()[0].reply_message(ReplyMessageRequest(reply_token=token, messages=[TextMessage(text=text[:4900], quick_reply=qr)]))


def push(user, text):
    if not os.getenv("LINE_CHANNEL_ACCESS_TOKEN"):
        SENT.append(text)
        return
    from linebot.v3.messaging import PushMessageRequest, TextMessage
    _api()[0].push_message(PushMessageRequest(to=user, messages=[TextMessage(text=text[:4900])]))


def image_bytes(message_id):
    return bytes(_api()[1].get_message_content(message_id))


def _state_path(user):
    p = core.data_dir() / "line_state"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{user}.json"


def get_state(user):
    p = _state_path(user)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def set_state(user, st):
    _state_path(user).write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def preview(job):
    if not job["deliveries"]:
        return f"【{job['text']['title']}】\n{job['text']['body']}\n\n⚠ 投稿先が未設定です（お店のスタッフに casts.yaml の portals を設定してもらってください）"
    return f"【{job['text']['title']}】\n{job['text']['body']}\n\n投稿先: {', '.join(job['deliveries'])}\nOK で投稿／やり直し／キャンセル"


def _deliver_bg(cfg, job, user):
    job = core.deliver(cfg, job)
    if cfg.get("line", {}).get("push_results", True):
        push(user, "投稿結果\n" + core.summary(job))


def handle(event, cfg, background=True):
    from linebot.v3.webhooks import FollowEvent, ImageMessageContent, MessageEvent, TextMessageContent
    user = getattr(event.source, "user_id", None)
    token = getattr(event, "reply_token", None)
    cast = core.find_cast(cfg, line_user_id=user)
    if isinstance(event, FollowEvent) or cast is None:
        if token:
            reply(token, f"未登録です。お店のスタッフにこのIDを伝えてください:\n{user}")
        return
    if not isinstance(event, MessageEvent):
        return
    st = get_state(user)
    msg = event.message
    if isinstance(msg, ImageMessageContent):
        d = core.data_dir() / "line_state"
        path = d / f"{user}_pending.jpg"
        path.write_bytes(image_bytes(msg.id))
        st.update(pending_photo=str(path))
        set_state(user, st)
        return reply(token, "写真を受け取りました📷\n一言メモを送ってください（例: 20時から出勤、雨の日割あり）")
    if not isinstance(msg, TextMessageContent):
        return
    text = msg.text.strip()
    job_id = st.get("awaiting")
    if text.lower() in {w.lower() for w in OK_WORDS} and job_id:
        job = core.load_job(job_id)
        st.pop("awaiting", None)
        set_state(user, st)
        reply(token, "投稿を始めます。終わったら結果をお知らせします")
        args = (cfg, job, user)
        threading.Thread(target=_deliver_bg, args=args, daemon=True).start() if background else _deliver_bg(*args)
        return
    if text in ("やり直し", "再生成") and job_id:
        job = core.load_job(job_id)
        job["text"] = core.write_text(cfg, cast, job["memo"])
        core.save_job(job)
        return reply(token, preview(job), ("OK", "やり直し", "キャンセル"))
    if text == "キャンセル":
        st.pop("awaiting", None)
        st.pop("pending_photo", None)
        set_state(user, st)
        return reply(token, "取り消しました")
    photo = st.get("pending_photo")
    if not photo and cfg.get("line", {}).get("require_photo", True):
        return reply(token, "先に写真を送ってください📷")
    try:
        job = core.create_job(cfg, cast, Path(photo).read_bytes() if photo else None, text, source="line")
    except PermissionError as e:
        return reply(token, f"投稿できません: {e}")
    st.pop("pending_photo", None)
    if cfg.get("approval", "line") == "none":
        set_state(user, st)
        reply(token, "投稿を始めます")
        args = (cfg, job, user)
        threading.Thread(target=_deliver_bg, args=args, daemon=True).start() if background else _deliver_bg(*args)
        return
    st["awaiting"] = job["id"]
    set_state(user, st)
    return reply(token, preview(job), ("OK", "やり直し", "キャンセル"))


@app.post("/callback")
async def callback(request: Request):
    from linebot.v3 import WebhookParser
    from linebot.v3.exceptions import InvalidSignatureError
    body = (await request.body()).decode("utf-8")
    try:
        events = WebhookParser(os.environ["LINE_CHANNEL_SECRET"]).parse(body, request.headers.get("x-line-signature", ""))
    except InvalidSignatureError:
        raise HTTPException(400, "invalid signature")
    cfg = core.load_config()
    for ev in events:
        try:
            handle(ev, cfg)
        except Exception as e:  # 1件の失敗で他のイベントを落とさない
            print(f"LINE イベント処理失敗: {e}")
    return "OK"


@app.get("/health")
def health():
    return {"ok": True}
