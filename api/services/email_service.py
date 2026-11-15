"""Emailing approved reports.

Two modes:
 - gmail:  real delivery through Gmail SMTP using GMAIL_ADDRESS + GMAIL_APP_PASSWORD
           (an App Password created in your Google account, never your normal password).
 - outbox: nothing is sent. The email is saved as a .eml file in the outbox folder.
           This is the default so demos and tests can never email anyone by accident.

Only the approved report PDF is attached. No scans or images are ever emailed.
"""
import logging
import smtplib
import ssl
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage

from ..config import DISCLAIMER, settings

log = logging.getLogger("celliq")

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 587


def build_message(recipient: str, patient_display_id: str, sender_name: str, pdf: bytes, filename: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Your CellIQ report ({patient_display_id})"
    msg["From"] = settings.gmail_address or "celliq-demo@localhost"
    msg["To"] = recipient
    msg.set_content(
        "Hello,\n\n"
        f"Your doctor ({sender_name}) has reviewed your scan results. The report is attached as a PDF.\n"
        "Please discuss it with your doctor. It is not a diagnosis.\n\n"
        f"{DISCLAIMER}\n"
    )
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=filename)
    return msg


def deliver(msg: EmailMessage) -> str:
    """Returns the mode used: 'gmail' or 'outbox'. Raises RuntimeError if Gmail delivery fails."""
    if settings.email_mode == "outbox":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        (settings.outbox_dir / f"{stamp}-{uuid.uuid4().hex[:8]}.eml").write_bytes(bytes(msg))
        return "outbox"
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings.gmail_address, settings.gmail_app_password)
            smtp.send_message(msg)
        return "gmail"
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("Gmail send failed (%s)", type(exc).__name__)
        raise RuntimeError("Could not send the email through Gmail. Check the app password and try again.") from exc
