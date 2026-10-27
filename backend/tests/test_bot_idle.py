from datetime import timedelta

from app import clock
from app.config import cfg
from app.db import SessionLocal
from app.models import AuditLog, SessionRow, User

from .conftest import admin_client, login, new_client

TRUSTED_IP = "203.0.113.9"


def bot():
    c = new_client()
    assert login(c, ip=TRUSTED_IP).json() == {"next": "app"}
    return c


def settings(**kw):
    adm = admin_client()
    r = adm.put("/api/dev/settings", json=kw)
    assert r.status_code == 200, r.text
    return adm


def user_flagged(username="bot_downtown"):
    with SessionLocal() as db:
        return db.query(User).filter_by(username=username).one().flagged


# --------------------------------------------------------------- request rate
def test_too_many_requests_per_minute_flags_the_session():
    settings(bot_max_requests_per_min=5, bot_min_action_ms=0)
    c = bot()
    codes = [c.get("/api/auth/me").status_code for _ in range(5)]
    assert codes == [200] * 5
    r = c.get("/api/auth/me")
    assert r.status_code == 403 and r.json()["code"] == "bot_detected"
    # session is gone
    r = c.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["code"] == "bot_detected"
    assert user_flagged()
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(event="bot_flag").count() == 1


def test_under_the_limit_is_fine():
    settings(bot_max_requests_per_min=10)
    c = bot()
    assert all(c.get("/api/auth/me").status_code == 200 for _ in range(10))


# --------------------------------------------------------------- fast form submissions
def test_six_fast_form_submissions_flag_the_session():
    settings(bot_min_action_ms=60_000)  # everything in a test is "too fast"
    c = bot()
    codes = [c.get("/api/patients", params={"q": "a"}).status_code for _ in range(5)]
    assert codes == [200] * 5
    r = c.get("/api/patients", params={"q": "a"})  # 6th in a row
    assert r.status_code == 403 and r.json()["code"] == "bot_detected"
    assert user_flagged()


def test_non_form_requests_do_not_count_as_form_submissions():
    settings(bot_min_action_ms=60_000)
    c = bot()
    assert all(c.get("/api/auth/me").status_code == 200 for _ in range(20))
    assert not user_flagged()


def test_slow_form_submissions_are_fine():
    settings(bot_min_action_ms=0)
    c = bot()
    assert all(c.get("/api/patients", params={"q": "a"}).status_code == 200 for _ in range(20))


def test_bot_detection_can_be_switched_off():
    settings(bot_detection=False, bot_min_action_ms=60_000, bot_max_requests_per_min=1)
    c = bot()
    assert all(c.get("/api/patients", params={"q": "a"}).status_code == 200 for _ in range(15))
    assert not user_flagged()


# --------------------------------------------------------------- consequences of a flag
def test_flag_forces_captcha_and_mfa_at_next_login(monkeypatch):
    cfg.captcha_provider = "enterprise"
    monkeypatch.setattr("app.routers.auth.verify_token", lambda t: t == "good")
    adm = admin_client()
    adm.put("/api/dev/settings", json={"bot_max_requests_per_min": 3, "captcha_mode": "never"})
    c = new_client()
    assert login(c, ip=TRUSTED_IP).json() == {"next": "app"}  # mode never: no captcha token needed
    for _ in range(4):
        c.get("/api/auth/me")
    assert user_flagged()

    info = c.post("/api/auth/identify", json={"organization": "sunrise", "username": "bot_downtown"}).json()
    assert info["captcha_required"] is True  # even in mode "never"
    assert login(c, ip=TRUSTED_IP).status_code == 400  # trusted IP, but no captcha
    r = login(c, ip=TRUSTED_IP, captcha="good")
    assert r.json() == {"next": "mfa", "mfa_step": "email"}  # MFA forced despite trusted IP


def test_flag_does_not_force_mfa_when_switched_off(monkeypatch):
    settings(bot_max_requests_per_min=3, bot_flag_forces_mfa=False)
    c = bot()
    for _ in range(4):
        c.get("/api/auth/me")
    assert user_flagged()
    assert login(c, ip=TRUSTED_IP).json() == {"next": "app"}
    assert not user_flagged()  # completing a login clears the flag


def test_flag_cleared_after_completed_login_with_mfa():
    settings(bot_max_requests_per_min=3)
    c = bot()
    for _ in range(4):
        c.get("/api/auth/me")
    assert login(c, ip=TRUSTED_IP).json()["next"] == "mfa"
    assert user_flagged()  # still flagged until MFA is done
    from .conftest import email_code, sms_code

    c.post("/api/auth/mfa/email", json={"code": email_code()})
    c.post("/api/auth/mfa/sms", json={"code": sms_code(c)})
    assert not user_flagged()


# --------------------------------------------------------------- idle timeout
def _age_session(minutes):
    with SessionLocal() as db:
        for s in db.query(SessionRow).filter(SessionRow.ended_reason.is_(None)):
            s.last_activity = clock.now() - timedelta(minutes=minutes)
        db.commit()


def test_idle_timeout_redirects_with_message():
    c = bot()
    assert c.get("/api/patients").status_code == 200
    _age_session(16)  # default 15 minutes
    r = c.get("/api/patients")
    assert r.status_code == 401
    assert r.json() == {"code": "idle_timeout", "message": "You were logged out due to inactivity"}
    # still reported on a page reload, then the session stays dead
    assert c.get("/api/auth/me").json()["code"] == "idle_timeout"
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(event="timeout").count() == 1


def test_activity_keeps_the_session_alive():
    c = bot()
    _age_session(14)
    assert c.get("/api/auth/me").status_code == 200  # refreshes last_activity
    _age_session(14)
    assert c.get("/api/auth/me").status_code == 200


def test_idle_timeout_is_a_runtime_setting():
    settings(idle_timeout_minutes=1)
    c = bot()
    _age_session(2)
    assert c.get("/api/auth/me").status_code == 401


def test_idle_also_applies_during_mfa():
    c = new_client()
    login(c, ip="198.51.100.7")
    _age_session(16)
    assert c.post("/api/auth/mfa/email", json={"code": "123456"}).json()["code"] == "idle_timeout"
