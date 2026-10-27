import logging
import smtplib
from email.message import EmailMessage

from .config import cfg

log = logging.getLogger("ledgerlab.mail")

# Used when SMTP_HOST is empty (tests): (to, subject, body)
OUTBOX: list[tuple[str, str, str]] = []


def send_email(to: str, subject: str, body: str) -> None:
    if not cfg.smtp_host:
        OUTBOX.append((to, subject, body))
        log.info("MAIL (no SMTP_HOST, kept in outbox) to=%s subject=%s body=%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"] = cfg.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=5) as smtp:
            smtp.send_message(msg)
    except Exception:  # Mailpit down must not break login; the SMS inbox / logs still work
        log.exception("Could not send email to %s via %s:%s", to, cfg.smtp_host, cfg.smtp_port)
