import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="ledgerlab-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["SMTP_HOST"] = ""  # keep mails in the in-memory outbox
os.environ["CAPTCHA_PROVIDER"] = "off"
os.environ["RECAPTCHA_PROJECT_ID"] = "test-project"
os.environ["RECAPTCHA_SITE_KEY"] = "test-site-key"
os.environ["RECAPTCHA_API_KEY"] = "test-api-key"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import mail  # noqa: E402
from app.config import cfg  # noqa: E402
from app.db import reset_db  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = cfg.seed_password


@pytest.fixture(autouse=True)
def fresh_db():
    reset_db()
    mail.OUTBOX.clear()
    cfg.captcha_provider = "off"
    yield


def new_client() -> TestClient:
    """A new 'browser' with its own cookie jar."""
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    return new_client()


def login(c, username="bot_downtown", password=PASSWORD, ip="198.51.100.7", captcha=None, org="sunrise"):
    body = {"organization": org, "username": username, "password": password}
    if captcha is not None:
        body["captcha_token"] = captcha
    return c.post("/api/auth/login", json=body, headers={"x-forwarded-for": ip})


def email_code() -> str:
    body = mail.OUTBOX[-1][2]
    return body.split("code is ")[1][:6]


def sms_code(c, user="bot_downtown") -> str:
    return c.get("/api/dev/sms/latest", params={"user": user}).json()["code"]


def full_login(c, username="bot_downtown", ip="198.51.100.7"):
    """Log in, passing MFA when asked, and pick the only location. Returns last response."""
    r = login(c, username, ip=ip)
    assert r.status_code == 200, r.text
    if r.json()["next"] == "mfa":
        r = c.post("/api/auth/mfa/email", json={"code": email_code()})
        assert r.status_code == 200, r.text
        if r.json()["next"] == "mfa":
            r = c.post("/api/auth/mfa/sms", json={"code": sms_code(c, username)})
            assert r.status_code == 200, r.text
    return r


def admin_client() -> TestClient:
    """Logged-in admin at Downtown. CAPTCHA is skipped so tests can switch it on afterwards."""
    provider = cfg.captcha_provider
    cfg.captcha_provider = "off"
    try:
        c = new_client()
        full_login(c, "admin")
    finally:
        cfg.captcha_provider = provider
    r = c.post("/api/auth/location", json={"location_id": 1})
    assert r.status_code == 200, r.text
    return c
