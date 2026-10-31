"""通知: Slack / Discord / Chatwork / メール(SMTP)。.env に設定がある宛先すべてへ送る。"""
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests


def _slack(text, attach, subject):
    requests.post(os.environ["SLACK_WEBHOOK_URL"], json={"text": text}, timeout=15).raise_for_status()


def _discord(text, attach, subject):
    requests.post(os.environ["DISCORD_WEBHOOK_URL"], json={"content": text[:1900]}, timeout=15).raise_for_status()


def _chatwork(text, attach, subject):
    requests.post(f"https://api.chatwork.com/v2/rooms/{os.environ['CHATWORK_ROOM_ID']}/messages",
                  headers={"X-ChatWorkToken": os.environ["CHATWORK_TOKEN"]}, data={"body": text}, timeout=15).raise_for_status()


def _mail(text, attach, subject):
    user = os.environ["SMTP_USER"]
    msg = MIMEMultipart()
    msg["Subject"], msg["From"], msg["To"] = subject, user, os.environ["MAIL_TO"]
    msg.attach(MIMEText(text, "plain", "utf-8"))
    if attach and Path(attach).exists():
        part = MIMEApplication(Path(attach).read_bytes(), Name=Path(attach).name)
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", Path(attach).name))
        msg.attach(part)
    with smtplib.SMTP_SSL(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "465"))) as s:
        s.login(user, os.environ["SMTP_PASSWORD"])
        s.send_message(msg)


CHANNELS = [("slack", ("SLACK_WEBHOOK_URL",), _slack), ("discord", ("DISCORD_WEBHOOK_URL",), _discord),
            ("chatwork", ("CHATWORK_TOKEN", "CHATWORK_ROOM_ID"), _chatwork), ("mail", ("SMTP_USER", "MAIL_TO"), _mail)]


def send(text: str, attach: str | None = None, subject: str = "【自動通知】"):
    """設定済みの全宛先へ。1つ失敗しても他は送る。"""
    sent = []
    for name, keys, fn in CHANNELS:
        if not all(os.getenv(k) for k in keys):
            continue
        try:
            fn(text, attach, subject)
            sent.append(name)
        except Exception as e:
            print(f"通知失敗 {name}: {e}")
    print(f"通知: {', '.join(sent) or '宛先なし/失敗（.env を確認）'}")
    return sent
