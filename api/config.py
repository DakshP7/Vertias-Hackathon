"""Central settings. Everything configurable comes from environment variables / .env."""
import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

log = logging.getLogger("celliq")

DISCLAIMER = (
    "CellIQ is a research and educational prototype. It supports, and does not replace, "
    "clinical judgement. Results are not a diagnosis and must be reviewed by a qualified doctor."
)


class Settings:
    def __init__(self) -> None:
        self.db_url = os.getenv("CELLIQ_DB", f"sqlite:///{BASE_DIR / 'data' / 'celliq.db'}")
        self.upload_dir = Path(os.getenv("CELLIQ_UPLOADS", str(BASE_DIR / "data" / "uploads")))
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        (BASE_DIR / "data").mkdir(exist_ok=True)

        secret = os.getenv("CELLIQ_JWT_SECRET")
        if not secret:
            secret = secrets.token_urlsafe(48)
            log.warning("CELLIQ_JWT_SECRET not set: using a random secret. Logins reset on restart.")
        self.jwt_secret = secret
        self.jwt_hours = int(os.getenv("CELLIQ_JWT_HOURS", "8"))

        self.cors_origins = [
            o.strip()
            for o in os.getenv("CELLIQ_CORS", "http://localhost:3000,http://localhost:5173").split(",")
            if o.strip()
        ]
        self.max_upload_mb = int(os.getenv("CELLIQ_MAX_UPLOAD_MB", "20"))
        self.ct_max_upload_mb = int(os.getenv("CELLIQ_CT_MAX_UPLOAD_MB", "600"))  # whole CT volumes are large

        # Triage thresholds. These are PLACEHOLDERS until chosen on validation data.
        self.threshold_high = float(os.getenv("CELLIQ_THRESHOLD_HIGH", "0.70"))
        self.threshold_review = float(os.getenv("CELLIQ_THRESHOLD_REVIEW", "0.40"))

        # Email sending. Gmail SMTP needs 2-step verification and an App Password (not your normal
        # password). Without credentials, emails are written to the outbox folder and NOT sent.
        self.gmail_address = os.getenv("GMAIL_ADDRESS", "")
        self.gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "")
        self.outbox_dir = Path(os.getenv("CELLIQ_OUTBOX", str(BASE_DIR / "data" / "outbox")))
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self.max_emails_per_hour = int(os.getenv("CELLIQ_MAX_EMAILS_PER_HOUR", "20"))

        # Gemini (optional). Without a key, reports fall back to a fixed template.
        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


    @property
    def email_mode(self) -> str:
        return "gmail" if self.gmail_address and self.gmail_app_password else "outbox"


settings = Settings()
