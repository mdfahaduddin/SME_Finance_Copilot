"""Outgoing email (password resets, team invitations).

With SMTP configured, mail is sent over STARTTLS. Without it (development), the message is
written to the application log so the link can be copied from there.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger("smecopilot.email")


def send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.email_enabled:
        log.info("Email (SMTP not configured) to=%s subject=%r\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError):
        # Never surface mail failures to the requester (it would leak whether the address exists).
        log.exception("Failed to send email to %s", to)
