from datetime import timedelta

from app import clock
from app.db import SessionLocal
from app.models import AuditLog, User

from .conftest import PASSWORD, admin_client, login, new_client

TRUSTED_IP = "203.0.113.9"  # inside the seeded trusted range


def _user(username):
    with SessionLocal() as db:
        return db.query(User).filter_by(username=username).one()


def _wrong(c, n, username="frontdesk_downtown"):
    last = None
    for _ in range(n):
        last = login(c, username, password="nope", ip=TRUSTED_IP)
    return last


def test_health():
    assert new_client().get("/api/health").json() == {"status": "ok"}


def test_login_success_from_trusted_ip_goes_straight_in(client):
    r = login(client, "frontdesk_downtown", ip=TRUSTED_IP)
    assert r.status_code == 200
    assert r.json() == {"next": "app"}  # single location is auto-selected
    assert client.get("/api/auth/me").json()["user"]["username"] == "frontdesk_downtown"


def test_session_cookie_is_http_only(client):
    r = login(client, "frontdesk_downtown", ip=TRUSTED_IP)
    assert "httponly" in r.headers["set-cookie"].lower()


def test_multi_location_user_must_choose_location(client):
    r = login(client, "admin", ip=TRUSTED_IP)
    assert r.json() == {"next": "location"}
    assert client.get("/api/patients").status_code == 409
    assert client.post("/api/auth/location", json={"location_id": 2}).json() == {"next": "app"}
    assert client.get("/api/patients").status_code == 200


def test_user_cannot_choose_foreign_location(client):
    login(client, "frontdesk_downtown", ip=TRUSTED_IP)
    assert client.post("/api/auth/location", json={"location_id": 2}).status_code == 403


def test_wrong_password_and_unknown_user_look_the_same(client):
    a = login(client, "frontdesk_downtown", password="bad", ip=TRUSTED_IP)
    b = login(client, "nobody", password="bad", ip=TRUSTED_IP)
    c = login(client, "frontdesk_downtown", password="bad", ip=TRUSTED_IP, org="other-org")
    assert a.status_code == b.status_code == c.status_code == 401
    assert a.json() == b.json() == c.json()


def test_organization_accepts_name_or_slug(client):
    assert login(client, "frontdesk_downtown", ip=TRUSTED_IP, org="Sunrise Dental Group").status_code == 200


def test_five_wrong_passwords_lock_for_five_minutes(client):
    r = _wrong(client, 5)
    assert r.status_code == 423 and r.json()["code"] == "account_locked"
    # Even the right password is refused while locked
    assert login(client, "frontdesk_downtown", ip=TRUSTED_IP).status_code == 423
    u = _user("frontdesk_downtown")
    assert timedelta(minutes=4) < u.locked_until - clock.now() <= timedelta(minutes=5)
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(event="lockout").count() == 1


def test_four_wrong_passwords_do_not_lock(client):
    r = _wrong(client, 4)
    assert r.status_code == 401
    assert login(client, "frontdesk_downtown", ip=TRUSTED_IP).status_code == 200


def test_lock_expires_after_five_minutes(client):
    _wrong(client, 5)
    with SessionLocal() as db:
        u = db.query(User).filter_by(username="frontdesk_downtown").one()
        u.locked_until = clock.now() - timedelta(seconds=1)
        db.commit()
    assert login(client, "frontdesk_downtown", ip=TRUSTED_IP).status_code == 200


def test_five_more_wrong_passwords_after_lock_block_the_account(client):
    _wrong(client, 5)
    with SessionLocal() as db:
        u = db.query(User).filter_by(username="frontdesk_downtown").one()
        u.locked_until = clock.now() - timedelta(seconds=1)
        db.commit()
    r = _wrong(client, 5)
    assert r.status_code == 403 and r.json()["code"] == "account_blocked"
    assert _user("frontdesk_downtown").status == "blocked"
    # stays blocked even after the 5 minutes and with the right password
    assert login(client, "frontdesk_downtown", ip=TRUSTED_IP).status_code == 403
    with SessionLocal() as db:
        events = [e for (e,) in db.query(AuditLog.event).all()]
    assert "lockout" in events and "account_blocked" in events


def test_admin_can_reactivate_blocked_user(client):
    _wrong(client, 5)
    with SessionLocal() as db:
        u = db.query(User).filter_by(username="frontdesk_downtown").one()
        u.locked_until = clock.now() - timedelta(seconds=1)
        db.commit()
    _wrong(client, 5)
    uid = _user("frontdesk_downtown").id
    adm = admin_client()
    assert adm.post(f"/api/dev/users/{uid}/reactivate").status_code == 200
    assert login(new_client(), "frontdesk_downtown", ip=TRUSTED_IP).status_code == 200


def test_successful_login_resets_the_failure_counter(client):
    _wrong(client, 4)
    assert login(client, "frontdesk_downtown", ip=TRUSTED_IP).status_code == 200
    r = _wrong(new_client(), 4)
    assert r.status_code == 401  # would be locked if the earlier 4 still counted


def test_logout_ends_session_and_is_audited(client):
    login(client, "frontdesk_downtown", ip=TRUSTED_IP)
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(event="logout").count() == 1


def test_login_attempts_are_audited_with_ip_and_result(client):
    login(client, "frontdesk_downtown", password="bad", ip=TRUSTED_IP)
    login(client, "frontdesk_downtown", ip=TRUSTED_IP)
    with SessionLocal() as db:
        rows = db.query(AuditLog).filter_by(event="login_attempt").order_by(AuditLog.id).all()
    assert [r.result for r in rows] == ["failure", "success"]
    assert all(r.ip == TRUSTED_IP and r.username == "frontdesk_downtown" for r in rows)


def test_patient_routes_need_a_session(client):
    assert client.get("/api/patients").status_code == 401
