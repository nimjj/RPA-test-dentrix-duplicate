from datetime import timedelta

from app import clock, mail
from app.db import SessionLocal
from app.models import AuditLog, MfaChallenge

from .conftest import admin_client, email_code, full_login, login, new_client, sms_code

TRUSTED_IP = "203.0.113.9"
OTHER_IP = "198.51.100.7"


def test_unknown_device_on_untrusted_ip_requires_mfa(client):
    r = login(client, ip=OTHER_IP)
    assert r.json() == {"next": "mfa", "mfa_step": "email"}
    # nothing in the app works before MFA is done
    assert client.get("/api/patients").status_code == 403
    assert client.get("/api/patients").json()["code"] == "mfa_required"


def test_email_code_goes_to_registered_address_and_is_six_digits(client):
    login(client, ip=OTHER_IP)
    to, subject, body = mail.OUTBOX[-1]
    assert to == "bot_downtown@sunrise.test"
    assert len(email_code()) == 6 and email_code().isdigit()
    assert "10 minutes" in body


def test_full_two_step_mfa_then_device_cookie(client):
    login(client, ip=OTHER_IP)
    r = client.post("/api/auth/mfa/email", json={"code": email_code()})
    assert r.json() == {"next": "mfa", "mfa_step": "sms"}
    code = sms_code(client)
    assert len(code) == 6
    r = client.post("/api/auth/mfa/sms", json={"code": code})
    assert r.json() == {"next": "app"}
    cookie = r.headers["set-cookie"].lower()
    assert "device_id=" in cookie and "httponly" in cookie and f"max-age={90 * 24 * 3600}" in cookie
    assert client.get("/api/patients").status_code == 200


def test_recognized_device_skips_mfa_on_next_login(client):
    full_login(client, ip=OTHER_IP)
    client.post("/api/auth/logout")
    mail.OUTBOX.clear()
    r = login(client, ip=OTHER_IP)
    assert r.json() == {"next": "app"}
    assert mail.OUTBOX == []


def test_other_browser_still_needs_mfa(client):
    full_login(client, ip=OTHER_IP)
    assert login(new_client(), ip=OTHER_IP).json()["next"] == "mfa"


def test_trusted_ip_skips_mfa_without_a_device(client):
    r = login(client, ip=TRUSTED_IP)
    assert r.json() == {"next": "app"}
    assert mail.OUTBOX == []


def test_wrong_email_code_is_rejected_and_audited(client):
    login(client, ip=OTHER_IP)
    r = client.post("/api/auth/mfa/email", json={"code": "000000" if email_code() != "000000" else "111111"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_code"
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(event="mfa_failed").count() == 1


def test_codes_cannot_be_reused(client):
    login(client, ip=OTHER_IP)
    code = email_code()
    assert client.post("/api/auth/mfa/email", json={"code": code}).status_code == 200
    # step 1 is over; replaying it is refused
    assert client.post("/api/auth/mfa/email", json={"code": code}).status_code == 403


def test_email_code_expires_after_ten_minutes(client):
    login(client, ip=OTHER_IP)
    with SessionLocal() as db:
        ch = db.query(MfaChallenge).filter_by(step="email").one()
        assert timedelta(minutes=9) < ch.expires_at - clock.now() <= timedelta(minutes=10)
        ch.expires_at = clock.now() - timedelta(seconds=1)
        db.commit()
    r = client.post("/api/auth/mfa/email", json={"code": email_code()})
    assert r.status_code == 400 and r.json()["code"] == "code_expired"


def test_five_wrong_codes_end_the_session(client):
    login(client, ip=OTHER_IP)
    for _ in range(5):
        r = client.post("/api/auth/mfa/email", json={"code": "abcdef"})
    assert r.status_code == 401 and r.json()["code"] == "mfa_failed"
    assert client.post("/api/auth/mfa/email", json={"code": email_code()}).status_code == 401


def test_resend_invalidates_the_previous_code(client):
    login(client, ip=OTHER_IP)
    first = email_code()
    assert client.post("/api/auth/mfa/resend").status_code == 200
    second = email_code()
    if first != second:
        assert client.post("/api/auth/mfa/email", json={"code": first}).status_code == 400
    assert client.post("/api/auth/mfa/email", json={"code": second}).status_code == 200


def test_sms_step_can_be_switched_off():
    adm = admin_client()
    assert adm.put("/api/dev/settings", json={"mfa_sms_step": False}).status_code == 200
    c = new_client()
    login(c, ip=OTHER_IP)
    r = c.post("/api/auth/mfa/email", json={"code": email_code()})
    assert r.json() == {"next": "app"}
    assert "device_id=" in r.headers["set-cookie"]


def test_sms_inbox_endpoint_404_for_unknown_user(client):
    assert client.get("/api/dev/sms/latest", params={"user": "ghost"}).status_code == 404


def test_admin_clears_devices_forcing_mfa_again(client):
    full_login(client, ip=OTHER_IP)
    client.post("/api/auth/logout")
    assert login(client, ip=OTHER_IP).json() == {"next": "app"}
    client.post("/api/auth/logout")
    adm = admin_client()
    users = adm.get("/api/dev/users").json()["users"]
    bot = next(u for u in users if u["username"] == "bot_downtown")
    assert bot["devices"] == 1
    adm.post(f"/api/dev/users/{bot['id']}/clear-devices")
    assert login(client, ip=OTHER_IP).json()["next"] == "mfa"


def test_trusted_ips_are_editable_per_organization(client):
    adm = admin_client()
    assert login(new_client(), ip=OTHER_IP).json()["next"] == "mfa"
    r = adm.put("/api/dev/org/trusted-ips", json={"ips": ["198.51.100.0/24"]})
    assert r.status_code == 200
    assert login(new_client(), ip=OTHER_IP).json() == {"next": "app"}
    assert adm.put("/api/dev/org/trusted-ips", json={"ips": ["not-an-ip"]}).status_code == 422


def test_mfa_events_are_audited(client):
    full_login(client, ip=OTHER_IP)
    with SessionLocal() as db:
        events = [e for (e,) in db.query(AuditLog.event).all()]
    assert events.count("mfa_sent") == 2 and events.count("mfa_passed") == 2
