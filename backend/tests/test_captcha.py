import pytest

from app import captcha
from app.config import cfg
from app.db import SessionLocal
from app.models import AuditLog, User

from .conftest import admin_client, full_login, login, new_client

TRUSTED_IP = "203.0.113.9"


@pytest.fixture
def enterprise(monkeypatch):
    cfg.captcha_provider = "enterprise"
    calls = []

    def fake_verify(token):
        calls.append(token)
        return token == "good"

    monkeypatch.setattr("app.routers.auth.verify_token", fake_verify)
    return calls


def identify(c, username="bot_downtown"):
    return c.post("/api/auth/identify", json={"organization": "sunrise", "username": username}).json()


def set_mode(mode):
    adm = admin_client()
    assert adm.put("/api/dev/settings", json={"captcha_mode": mode}).status_code == 200


def test_provider_off_never_needs_captcha(client):
    set_mode("always")
    assert identify(client)["captcha_required"] is False
    assert login(client, ip=TRUSTED_IP).status_code == 200


def test_new_device_mode_default(enterprise, client):
    info = identify(client)
    assert info["captcha_required"] is True
    assert info["captcha_provider"] == "enterprise"
    assert info["site_key"] == "test-site-key"


def test_never_mode(enterprise, client):
    set_mode("never")
    assert identify(client)["captcha_required"] is False
    assert login(client, ip=TRUSTED_IP).status_code == 200
    assert enterprise == []


def test_always_mode_even_on_known_device(enterprise, client):
    login(client, captcha="good", ip="198.51.100.7")
    from .conftest import email_code, sms_code

    client.post("/api/auth/mfa/email", json={"code": email_code()})
    client.post("/api/auth/mfa/sms", json={"code": sms_code(client)})
    client.post("/api/auth/logout")
    assert identify(client)["captcha_required"] is False  # known device, new_device mode
    set_mode("always")
    assert identify(client)["captcha_required"] is True


def test_new_device_mode_skips_captcha_on_second_login(enterprise, client):
    assert login(client, ip=TRUSTED_IP, captcha="good").status_code == 200
    # trusted IP skips MFA so no device cookie was issued: still a new device
    client.post("/api/auth/logout")
    assert identify(client)["captcha_required"] is True
    # complete a login with MFA to become a recognized device
    c = new_client()
    full = login(c, ip="198.51.100.7", captcha="good")
    assert full.json()["next"] == "mfa"
    from .conftest import email_code, sms_code

    c.post("/api/auth/mfa/email", json={"code": email_code()})
    c.post("/api/auth/mfa/sms", json={"code": sms_code(c)})
    c.post("/api/auth/logout")
    assert identify(c)["captcha_required"] is False
    assert login(c, ip="198.51.100.7").json() == {"next": "app"}  # no captcha token, no MFA


def test_after_flag_mode_only_for_flagged_accounts(enterprise, client):
    set_mode("after_flag")
    assert identify(client)["captcha_required"] is False
    with SessionLocal() as db:
        db.query(User).filter_by(username="bot_downtown").one().flagged = True
        db.commit()
    assert identify(client)["captcha_required"] is True
    assert identify(client, "bot_lakeside")["captcha_required"] is False


def test_missing_or_bad_token_is_rejected(enterprise, client):
    r = login(client, ip=TRUSTED_IP)
    assert r.status_code == 400 and r.json()["code"] == "captcha_failed"
    r = login(client, ip=TRUSTED_IP, captcha="bad")
    assert r.status_code == 400
    assert login(client, ip=TRUSTED_IP, captcha="good").status_code == 200


def test_captcha_is_checked_before_the_password(enterprise, client):
    for _ in range(10):
        r = login(client, password="wrong", ip=TRUSTED_IP, captcha="bad")
        assert r.json()["code"] == "captcha_failed"
    with SessionLocal() as db:
        u = db.query(User).filter_by(username="bot_downtown").one()
        assert u.failed_count == 0 and u.status == "active" and u.locked_until is None
    # a good token with a wrong password does reach the password check
    r = login(client, password="wrong", ip=TRUSTED_IP, captcha="good")
    assert r.json()["code"] == "invalid_credentials"


def test_captcha_events_are_audited(enterprise, client):
    identify(client)
    login(client, ip=TRUSTED_IP, captcha="bad")
    login(client, ip=TRUSTED_IP, captcha="good")
    with SessionLocal() as db:
        events = [e for (e,) in db.query(AuditLog.event).all()]
    assert events.count("captcha_shown") == 1
    assert events.count("captcha_failed") == 1
    assert events.count("captcha_passed") == 1


def test_enterprise_assessment_call(monkeypatch):
    cfg.captcha_provider = "enterprise"
    seen = {}

    class Resp:
        def __init__(self, valid):
            self.valid = valid

        def raise_for_status(self):
            pass

        def json(self):
            return {"tokenProperties": {"valid": self.valid}}

    def fake_post(url, params=None, json=None, timeout=None):
        seen.update(url=url, params=params, json=json)
        return Resp(seen.get("next_valid", True))

    monkeypatch.setattr(captcha.httpx, "post", fake_post)
    assert captcha.verify_token("tok") is True
    assert seen["url"].endswith("/projects/test-project/assessments")
    assert seen["params"] == {"key": "test-api-key"}
    assert seen["json"] == {"event": {"token": "tok", "siteKey": "test-site-key"}}
    seen["next_valid"] = False
    assert captcha.verify_token("tok") is False
    assert captcha.verify_token("") is False


def test_enterprise_http_error_fails_closed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(captcha.httpx, "post", boom)
    assert captcha.verify_token("tok") is False


def test_google_test_provider_uses_default_test_key_and_siteverify(monkeypatch, client):
    monkeypatch.setattr(cfg, "captcha_provider", "test")
    monkeypatch.setattr(cfg, "recaptcha_site_key", "")
    info = identify(client)
    assert info["captcha_required"] is True
    assert info["captcha_provider"] == "test"
    assert info["site_key"] == captcha.GOOGLE_TEST_SITE_KEY

    seen = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"success": True}

    def fake_post(url, data=None, timeout=None):
        seen.update(url=url, data=data)
        return Resp()

    monkeypatch.setattr(captcha.httpx, "post", fake_post)
    assert captcha.verify_token("test-token") is True
    assert seen["url"] == captcha.SITEVERIFY_URL
    assert seen["data"] == {"secret": captcha.GOOGLE_TEST_SECRET_KEY, "response": "test-token"}
