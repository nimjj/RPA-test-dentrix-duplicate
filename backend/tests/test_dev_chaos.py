import app.main as main_module
from app.db import SessionLocal
from app.models import AuditLog

from .conftest import admin_client, login, new_client

TRUSTED_IP = "203.0.113.9"


def test_dev_settings_require_admin(client):
    assert client.get("/api/dev/settings").status_code == 401
    login(client, "frontdesk_downtown", ip=TRUSTED_IP)
    assert client.get("/api/dev/settings").status_code == 403


def test_settings_roundtrip_and_validation():
    adm = admin_client()
    s = adm.get("/api/dev/settings").json()
    assert s["settings"]["captcha_mode"] == "new_device"
    assert s["settings"]["idle_timeout_minutes"] == 15
    assert s["settings"]["bot_max_requests_per_min"] == 60
    assert s["settings"]["bot_min_action_ms"] == 400
    assert s["settings"]["mfa_sms_step"] is True and s["settings"]["bot_detection"] is True
    r = adm.put("/api/dev/settings", json={"captcha_mode": "always", "idle_timeout_minutes": 5})
    assert r.json()["settings"]["captcha_mode"] == "always"
    assert adm.put("/api/dev/settings", json={"captcha_mode": "sometimes"}).status_code == 422
    assert adm.put("/api/dev/settings", json={"idle_timeout_minutes": 0}).status_code == 422
    assert adm.put("/api/dev/settings", json={"nonsense": 1}).status_code == 422
    assert adm.put("/api/dev/settings", json={"bot_detection": "yes"}).status_code == 422
    assert adm.get("/api/dev/settings").json()["settings"]["captcha_mode"] == "always"  # no restart needed


# ------------------------------------------------------------------ outage
def test_outage_mode_returns_503_except_dev_settings():
    adm = admin_client()
    bot = new_client()
    assert login(bot, "bot_downtown", ip=TRUSTED_IP).status_code == 200
    adm.put("/api/dev/settings", json={"chaos_outage": True})

    for path in ("/api/patients", "/api/patients/DT-100234/ledger", "/api/locations/current/payment-types"):
        r = bot.get(path)
        assert r.status_code == 503, path
        assert r.json()["maintenance"] is True
    r = new_client().post("/api/auth/login", json={"organization": "sunrise", "username": "bot_downtown", "password": "x"})
    assert r.status_code == 503
    assert new_client().post("/api/auth/identify", json={"organization": "sunrise", "username": "bot_downtown"}).status_code == 503

    # exempt
    assert new_client().get("/api/health").status_code == 200
    assert new_client().get("/api/public-config").json()["outage"] is True
    assert adm.get("/api/dev/settings").status_code == 200
    # an admin can still log in to switch it off again
    adm2 = new_client()
    assert login(adm2, "admin", ip=TRUSTED_IP).status_code == 200
    assert adm2.put("/api/dev/settings", json={"chaos_outage": False}).status_code == 200
    assert bot.get("/api/patients").status_code == 200


def test_shell_check_gives_503_page_during_outage():
    c = new_client()
    r = c.get("/api/_shell")
    assert r.status_code == 200 and r.headers["x-accel-redirect"] == "/_spa/index.html"
    admin_client().put("/api/dev/settings", json={"chaos_outage": True})
    r = c.get("/api/_shell")
    assert r.status_code == 503 and "maintenance" in r.text.lower()
    for uri in ("/login", "/patients", "/", "/login?dev=0"):
        assert c.get("/api/_shell", headers={"x-original-uri": uri}).status_code == 503, uri
    # the admin way back in stays reachable
    for uri in ("/dev/settings", "/dev/audit", "/dev/sms", "/login?dev=1", "/login?x=1&dev=1"):
        assert c.get("/api/_shell", headers={"x-original-uri": uri}).status_code == 200, uri


# ------------------------------------------------------------------ slow mode
def test_slow_mode_delays_api_responses(monkeypatch):
    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(main_module.asyncio, "sleep", fake_sleep)
    bot = new_client()
    login(bot, "bot_downtown", ip=TRUSTED_IP)
    adm = admin_client()
    bot.get("/api/patients")
    assert delays == []
    adm.put("/api/dev/settings", json={"chaos_slow": True})
    for _ in range(20):
        bot.get("/api/auth/me")
    assert len(delays) == 20 and all(0.5 <= d <= 4.0 for d in delays)
    assert len(set(delays)) > 1  # random, not constant
    n = len(delays)
    adm.get("/api/dev/settings")
    new_client().get("/api/health")
    assert len(delays) == n  # dev tools and health stay fast


# ------------------------------------------------------------------ UI changed
def test_ui_changed_flag_is_published_to_the_frontend():
    assert new_client().get("/api/public-config").json()["ui_changed"] is False
    admin_client().put("/api/dev/settings", json={"chaos_ui_changed": True})
    assert new_client().get("/api/public-config").json()["ui_changed"] is True


# ------------------------------------------------------------------ reset + audit viewer
def test_reset_database_restores_seed_data():
    adm = admin_client()
    bot = new_client()
    login(bot, "bot_downtown", ip=TRUSTED_IP)
    types = bot.get("/api/locations/current/payment-types").json()["payment_types"]
    before = bot.get("/api/patients/DT-100234/ledger").json()
    bot.post("/api/patients/DT-100234/payments",
             json={"payment_type_id": types[0]["id"], "amount": "5.00", "payment_date": "2026-10-20"})
    adm.put("/api/dev/settings", json={"captcha_mode": "always"})
    assert adm.post("/api/dev/reset-db").status_code == 200
    bot2 = new_client()
    login(bot2, "bot_downtown", ip=TRUSTED_IP)
    after = bot2.get("/api/patients/DT-100234/ledger").json()
    assert after["entries"] == before["entries"]
    adm2 = admin_client()
    assert adm2.get("/api/dev/settings").json()["settings"]["captcha_mode"] == "new_device"


def test_audit_viewer_filters():
    adm = admin_client()
    login(new_client(), "bot_downtown", password="bad", ip=TRUSTED_IP)
    login(new_client(), "bot_lakeside", ip=TRUSTED_IP)
    all_rows = adm.get("/api/dev/audit").json()
    assert all_rows["total"] == len(all_rows["rows"]) > 0
    assert "login_attempt" in all_rows["events"]
    fails = adm.get("/api/dev/audit", params={"event": "login_attempt", "result": "failure"}).json()
    assert fails["total"] >= 1 and all(r["result"] == "failure" for r in fails["rows"])
    mine = adm.get("/api/dev/audit", params={"user": "bot_lakeside"}).json()
    assert mine["rows"] and all(r["user"] == "bot_lakeside" for r in mine["rows"])
    first = all_rows["rows"][0]
    assert {"time", "event", "user", "location", "ip", "result", "detail"} <= set(first)
    assert adm.get("/api/dev/audit", params={"q": TRUSTED_IP}).json()["total"] >= 2
    page = adm.get("/api/dev/audit", params={"limit": 2, "offset": 0}).json()
    assert len(page["rows"]) == 2 and page["total"] == all_rows["total"]


def test_every_required_event_type_reaches_the_audit_log():
    """login, captcha, mfa, lockout, bot flag, logout, timeout, search, ledger, payment."""
    from datetime import timedelta

    from app import clock
    from app.config import cfg
    from app.models import SessionRow

    from .conftest import email_code, sms_code

    adm = admin_client()
    adm.put("/api/dev/settings", json={"bot_max_requests_per_min": 8})

    cfg.captcha_provider = "enterprise"
    import app.routers.auth as auth_mod

    orig = auth_mod.verify_token
    auth_mod.verify_token = lambda t: t == "good"
    try:
        c = new_client()
        login(c, "bot_downtown", ip="198.51.100.7", captcha="bad")
        c.post("/api/auth/identify", json={"organization": "sunrise", "username": "bot_downtown"})
        login(c, "bot_downtown", ip="198.51.100.7", captcha="good")
    finally:
        auth_mod.verify_token = orig
        cfg.captcha_provider = "off"
    c.post("/api/auth/mfa/email", json={"code": email_code()})
    c.post("/api/auth/mfa/sms", json={"code": sms_code(c)})
    c.get("/api/patients", params={"q": "DT-100234"})
    c.get("/api/patients/DT-100234/ledger")
    t = c.get("/api/locations/current/payment-types").json()["payment_types"]
    c.post("/api/patients/DT-100234/payments",
           json={"payment_type_id": t[0]["id"], "amount": "1.00", "payment_date": "2026-10-20"})
    c.post("/api/auth/logout")

    for _ in range(5):
        login(new_client(), "frontdesk_downtown", password="bad", ip=TRUSTED_IP)  # lockout

    c2 = new_client()
    login(c2, "bot_lakeside", ip=TRUSTED_IP)
    with SessionLocal() as db:
        for s in db.query(SessionRow).filter(SessionRow.ended_reason.is_(None)):
            if s.user_id != 1:
                s.last_activity = clock.now() - timedelta(minutes=30)
        db.commit()
    c2.get("/api/auth/me")  # timeout

    c3 = new_client()
    login(c3, "bot_lakeside", ip=TRUSTED_IP)
    for _ in range(10):
        c3.get("/api/auth/me")  # bot flag

    with SessionLocal() as db:
        events = {e for (e,) in db.query(AuditLog.event).distinct()}
    expected = {"login_attempt", "captcha_shown", "captcha_passed", "captcha_failed", "mfa_sent", "mfa_passed",
                "lockout", "bot_flag", "logout", "timeout", "patient_search", "ledger_view", "payment"}
    assert expected <= events, expected - events
