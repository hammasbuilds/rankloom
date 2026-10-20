"""Outgoing mail. SMTP when it is configured; otherwise the message goes to the outbox table and
the server console, so password resets work on a development machine with no mail server and the
person running it can see exactly what would have been sent."""

from __future__ import annotations

import os
import smtplib
import ssl
import sys
import re
from email.message import EmailMessage

from .db import Database, now


_SECRET = re.compile(r"([?&]token=)[^\s&]+")


def smtp_configured() -> bool:
    return bool(os.environ.get("RANKLOOM_SMTP_HOST"))


def send(db: Database, to: str, subject: str, body: str) -> str:
    """Deliver or record a message. Returns 'smtp' or 'outbox'.

    With SMTP the outbox is only a log, so it keeps the message with its secret links blanked:
    a database backup must not hold working reset links. Without SMTP the outbox is how the
    link reaches the person running the server, so there it is kept whole.
    """
    logged = body if not smtp_configured() else _SECRET.sub(r"\1[sent by email]", body)
    db.run(
        "INSERT INTO outbox (to_email, subject, body, created_at) VALUES (?, ?, ?, ?)",
        to,
        subject,
        logged,
        now(),
    )
    if not smtp_configured():
        print(f"\n[rankloom mail -> {to}] {subject}\n{body}\n", file=sys.stderr, flush=True)
        return "outbox"
    msg = EmailMessage()
    msg["From"] = os.environ.get("RANKLOOM_SMTP_FROM", "Rankloom <no-reply@localhost>")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    host = os.environ["RANKLOOM_SMTP_HOST"]
    port = int(os.environ.get("RANKLOOM_SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        user = os.environ.get("RANKLOOM_SMTP_USER")
        if user:
            smtp.login(user, os.environ.get("RANKLOOM_SMTP_PASSWORD", ""))
        smtp.send_message(msg)
    return "smtp"
