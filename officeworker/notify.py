"""通知: Slack / Discord / Chatwork / メール(SMTP)。.env に設定がある宛先すべてへ送る。"""
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests


def send(text: str, attach: str | None = None, subject: str = "【自動通知】"):
    sent = []
    if u := os.getenv("SLACK_WEBHOOK_URL"):
        requests.post(u, json={"text": text}, timeout=15); sent.append("slack")
    if u := os.getenv("DISCORD_WEBHOOK_URL"):
        requests.post(u, json={"content": text[:1900]}, timeout=15); sent.append("discord")
    if (tok := os.getenv("CHATWORK_TOKEN")) and (room := os.getenv("CHATWORK_ROOM_ID")):
        requests.post(f"https://api.chatwork.com/v2/rooms/{room}/messages", headers={"X-ChatWorkToken": tok},
                      data={"body": text}, timeout=15); sent.append("chatwork")
    if (user := os.getenv("SMTP_USER")) and (to := os.getenv("MAIL_TO")):
        msg = MIMEMultipart()
        msg["Subject"], msg["From"], msg["To"] = subject, user, to
        msg.attach(MIMEText(text, "plain", "utf-8"))
        if attach and Path(attach).exists():
            part = MIMEApplication(Path(attach).read_bytes(), Name=Path(attach).name)
            part["Content-Disposition"] = f'attachment; filename="{Path(attach).name}"'
            msg.attach(part)
        with smtplib.SMTP_SSL(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "465"))) as s:
            s.login(user, os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
        sent.append("mail")
    print(f"通知: {', '.join(sent) or '宛先未設定（.env）'}")
    return sent
