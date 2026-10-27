"""Static configuration read from the environment (.env via docker compose).

Values that the Dev Settings page can change at runtime live in the `setting`
table; the numbers here are only their defaults (see runtime_settings.py).
"""
import os


def _str(name: str, default: str) -> str:
    v = os.environ.get(name)
    return default if v is None or v.strip() == "" else v.strip()


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return int(v)


class Config:
    def __init__(self) -> None:
        self.database_url = _str("DATABASE_URL", "sqlite:///./ledgerlab.db")
        self.seed_password = _str("SEED_PASSWORD", "LedgerLab!2026")
        self.bcrypt_rounds = _int("BCRYPT_ROUNDS", 12)
        self.default_trusted_ips = [
            s.strip() for s in _str("DEFAULT_TRUSTED_IPS", "203.0.113.0/24").split(",") if s.strip()
        ]
        self.cookie_secure = _bool("COOKIE_SECURE", False)

        # CAPTCHA
        self.captcha_provider = _str("CAPTCHA_PROVIDER", "off").lower()  # off | enterprise
        self.recaptcha_project_id = _str("RECAPTCHA_PROJECT_ID", "")
        self.recaptcha_site_key = _str("RECAPTCHA_SITE_KEY", "")
        self.recaptcha_api_key = _str("RECAPTCHA_API_KEY", "")

        # Mail (Mailpit). Empty SMTP_HOST keeps mails in an in-memory outbox (tests).
        self.smtp_host = os.environ.get("SMTP_HOST", "mailpit").strip()
        self.smtp_port = _int("SMTP_PORT", 1025)
        self.mail_from = _str("MAIL_FROM", "no-reply@ledgerlab.test")

        # Defaults for runtime-changeable settings
        self.default_settings = {
            "captcha_mode": _str("CAPTCHA_MODE", "new_device").lower(),
            "mfa_sms_step": _bool("MFA_SMS_STEP", True),
            "idle_timeout_minutes": _int("IDLE_TIMEOUT_MINUTES", 15),
            "bot_detection": _bool("BOT_DETECTION", True),
            "bot_max_requests_per_min": _int("BOT_MAX_REQUESTS_PER_MIN", 60),
            "bot_min_action_ms": _int("BOT_MIN_ACTION_MS", 400),
            "bot_flag_forces_mfa": _bool("BOT_FLAG_FORCES_MFA", True),
            "chaos_slow": False,
            "chaos_outage": False,
            "chaos_ui_changed": False,
        }


cfg = Config()
