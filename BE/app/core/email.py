"""Shared SMTP sender. If SMTP_HOST is unset (default in dev), emails are
printed to the console instead of sent — no local mail server needed to
develop notifications/shift-reports/invites.
"""
import smtplib
import sys
from email.message import EmailMessage

from app.core.config import settings


def send_email(to: list[str], subject: str, html_body: str) -> None:
    if not to:
        return

    if not settings.SMTP_HOST:
        text = f"[email:dev-mode] to={to} subject={subject!r}\n{html_body}\n"
        try:
            print(text)
        except UnicodeEncodeError:
            # Windows consoles default to a non-UTF-8 codepage (e.g. cp1252),
            # which can't encode characters like "→" that show up in trend
            # evidence text ("vibration 2.1 → 4.8 mm/s"). Never let a display
            # encoding issue crash the request that triggered a real alert —
            # degrade to a safe, readable substitution instead.
            encoding = sys.stdout.encoding or "ascii"
            print(text.encode(encoding, errors="replace").decode(encoding))
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = ", ".join(to)
    msg.set_content("This email requires an HTML-capable client.")
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(settings.SMTP_HOST, int(settings.SMTP_PORT)) as server:
            server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
    except Exception as exc:
        # Never let a transient email error crash the request that triggered
        # it (e.g. signup, invite).  Log and move on.
        import structlog
        structlog.get_logger(__name__).warning("email_send_failed", to=to, subject=subject, error=str(exc))
