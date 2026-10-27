from decimal import Decimal

import pytest

from app.db import SessionLocal
from app.models import AuditLog, LedgerEntry, Patient

from .conftest import admin_client, login, new_client

TRUSTED_IP = "203.0.113.9"
DT_ACCT = "DT-100234"


@pytest.fixture
def dt():
    """Downtown automation user."""
    c = new_client()
    assert login(c, "bot_downtown", ip=TRUSTED_IP).json() == {"next": "app"}
    return c


@pytest.fixture
def ls():
    c = new_client()
    assert login(c, "bot_lakeside", ip=TRUSTED_IP).json() == {"next": "app"}
    return c


def types(c):
    return {t["label"]: t["id"] for t in c.get("/api/locations/current/payment-types").json()["payment_types"]}


def pay(c, acct=DT_ACCT, amount="125.40", label="Visa", date="2026-10-20", note="txn 8841", apply_to="account_balance", **kw):
    return c.post(
        f"/api/patients/{acct}/payments",
        json={"payment_type_id": types(c)[label], "amount": amount, "payment_date": date,
              "apply_to": apply_to, "note": note, **kw},
    )


def ledger(c, acct=DT_ACCT, q=""):
    return c.get(f"/api/patients/{acct}/ledger", params={"q": q}).json()


# ------------------------------------------------------------------ seed + search
def test_seed_counts():
    with SessionLocal() as db:
        assert db.query(Patient).filter(Patient.account_no.like("DT-%")).count() == 20
        assert db.query(Patient).filter(Patient.account_no.like("LS-%")).count() == 20
        assert db.query(Patient).filter(Patient.id != Patient.guarantor_id).count() > 0  # families exist


def test_search_by_account_number(dt):
    res = dt.get("/api/patients", params={"q": DT_ACCT}).json()["results"]
    assert [p["account_no"] for p in res] == [DT_ACCT]
    assert Decimal(res[0]["balance"]) >= 0


def test_search_by_account_number_is_case_insensitive(dt):
    assert len(dt.get("/api/patients", params={"q": "dt-100234"}).json()["results"]) == 1


def test_search_by_name(dt):
    p = dt.get("/api/patients", params={"q": DT_ACCT}).json()["results"][0]
    for q in (p["last_name"], p["first_name"], f"{p['last_name']}, {p['first_name']}", p["first_name"].lower()):
        found = [x["account_no"] for x in dt.get("/api/patients", params={"q": q}).json()["results"]]
        assert DT_ACCT in found


def test_search_is_scoped_to_the_current_location(dt, ls):
    all_dt = dt.get("/api/patients").json()["results"]
    all_ls = ls.get("/api/patients").json()["results"]
    assert len(all_dt) == len(all_ls) == 20
    assert all(p["account_no"].startswith("DT-") for p in all_dt)
    assert all(p["account_no"].startswith("LS-") for p in all_ls)
    ls_acct = all_ls[0]["account_no"]
    assert dt.get("/api/patients", params={"q": ls_acct}).json()["results"] == []


def test_patient_of_other_location_is_not_reachable(dt, ls):
    ls_acct = ls.get("/api/patients").json()["results"][0]["account_no"]
    assert dt.get(f"/api/patients/{ls_acct}").status_code == 404
    assert dt.get(f"/api/patients/{ls_acct}/ledger").status_code == 404
    assert pay(dt, ls_acct).status_code == 404
    with SessionLocal() as db:
        assert db.query(LedgerEntry).filter_by(created_by="bot_downtown").count() == 0


def test_guarantor_is_returned(dt):
    results = dt.get("/api/patients").json()["results"]
    selfs = [p for p in results if p["guarantor"]["is_self"]]
    deps = [p for p in results if not p["guarantor"]["is_self"]]
    assert selfs and deps
    assert deps[0]["guarantor"]["account_no"].startswith("DT-")


# ------------------------------------------------------------------ ledger
def test_ledger_newest_first_with_running_balance(dt):
    data = ledger(dt)
    rows = data["entries"]
    assert len(rows) >= 2
    assert [r["date"] for r in rows] == sorted((r["date"] for r in rows), reverse=True)
    # newest row's running balance equals the patient balance; walking back removes each amount
    assert rows[0]["balance"] == data["patient"]["balance"]
    for newer, older in zip(rows, rows[1:]):
        assert Decimal(newer["balance"]) - Decimal(newer["amount"]) == Decimal(older["balance"])
    assert Decimal(rows[-1]["balance"]) == Decimal(rows[-1]["amount"])
    assert {r["type"] for r in rows} <= {"charge", "payment", "adjustment"}


def test_ledger_note_filter(dt):
    pay(dt, note="TXN-ABC-123")
    pay(dt, note="something else")
    found = ledger(dt, q="txn-abc")["entries"]
    assert len(found) == 1 and found[0]["note"] == "TXN-ABC-123"
    assert ledger(dt, q="no such text")["entries"] == []
    # filtering does not change running balances
    full = {r["id"]: r["balance"] for r in ledger(dt)["entries"]}
    assert full[found[0]["id"]] == found[0]["balance"]


# ------------------------------------------------------------------ payments
def test_post_125_40_visa_payment_shows_up_with_right_balance(dt):
    before = Decimal(ledger(dt)["patient"]["balance"])
    r = pay(dt, amount="125.40", note="POS 7731")
    assert r.status_code == 201, r.text
    assert r.json()["entry"]["amount"] == "-125.40"
    data = ledger(dt)
    top = data["entries"][0] if data["entries"][0]["note"] == "POS 7731" else next(
        e for e in data["entries"] if e["note"] == "POS 7731")
    assert top["amount"] == "-125.40"
    assert top["type"] == "payment" and top["payment_type"] == "Visa"
    assert Decimal(data["patient"]["balance"]) == before - Decimal("125.40")
    assert r.json()["balance"] == data["patient"]["balance"]
    assert str(before - Decimal("125.40")).count(".") == 1


def test_amounts_keep_exact_cents(dt):
    before = Decimal(ledger(dt)["patient"]["balance"])
    for amt in ("0.10", "0.20", "33.33", "7.05"):
        assert pay(dt, amount=amt).status_code == 201
    assert Decimal(ledger(dt)["patient"]["balance"]) == before - Decimal("40.68")


@pytest.mark.parametrize("amount", ["0", "0.00", "-5.00", "12.345", "abc", ""])
def test_bad_amounts_are_rejected(dt, amount):
    n = len(ledger(dt)["entries"])
    r = pay(dt, amount=amount)
    assert r.status_code == 422 and r.json()["code"] == "invalid_amount"
    assert len(ledger(dt)["entries"]) == n


def test_amount_is_never_rounded(dt):
    assert pay(dt, amount="10.005").status_code == 422


def test_note_limit_is_255(dt):
    assert pay(dt, note="x" * 255).status_code == 201
    r = pay(dt, note="x" * 256)
    assert r.status_code == 422 and r.json()["code"] == "note_too_long"


def test_apply_to_values(dt):
    assert pay(dt, apply_to="todays_visit").status_code == 201
    assert pay(dt, apply_to="elsewhere").status_code == 422


def test_duplicates_are_not_prevented(dt):
    before = len(ledger(dt)["entries"])
    assert pay(dt, note="same txn").status_code == 201
    assert pay(dt, note="same txn").status_code == 201
    assert len(ledger(dt, q="same txn")["entries"]) == 2
    assert len(ledger(dt)["entries"]) == before + 2


def test_payment_type_must_belong_to_the_location(dt, ls):
    foreign_id = types(ls)["VISA - Front Desk"]
    r = dt.post(f"/api/patients/{DT_ACCT}/payments",
                json={"payment_type_id": foreign_id, "amount": "5.00", "payment_date": "2026-10-20"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_payment_type"


def test_payment_types_are_renamed_per_location(dt, ls):
    assert "Visa" in types(dt) and "VISA - Front Desk" not in types(dt)
    assert "VISA - Front Desk" in types(ls) and "Visa" not in types(ls)
    assert len(types(dt)) == len(types(ls)) == 6


def test_locked_dates_are_rejected_with_a_clear_message(dt):
    adm = admin_client()
    assert adm.put("/api/dev/locations/1", json={"lock_before_date": "2026-10-01"}).status_code == 200
    r = pay(dt, date="2026-09-30")
    assert r.status_code == 422 and r.json()["code"] == "date_locked"
    assert "2026-10-01" in r.json()["message"] and "Downtown" in r.json()["message"]
    assert pay(dt, date="2026-10-01").status_code == 201  # the lock date itself is open


def test_lock_date_is_per_location(dt, ls):
    adm = admin_client()
    adm.put("/api/dev/locations/1", json={"lock_before_date": "2026-10-01"})
    assert pay(dt, date="2026-09-01").status_code == 422
    ls_acct = ls.get("/api/patients").json()["results"][0]["account_no"]
    assert pay(ls, acct=ls_acct, label="VISA - Front Desk", date="2026-09-01").status_code == 201


def test_lock_date_can_be_cleared(dt):
    adm = admin_client()
    adm.put("/api/dev/locations/1", json={"lock_before_date": "2026-10-01"})
    adm.put("/api/dev/locations/1", json={"lock_before_date": None})
    assert pay(dt, date="2020-01-01").status_code == 201


def test_payment_and_lookups_are_audited(dt):
    dt.get("/api/patients", params={"q": DT_ACCT})
    ledger(dt)
    pay(dt, note="audited")
    pay(dt, amount="0")
    with SessionLocal() as db:
        rows = db.query(AuditLog).filter(AuditLog.user_id.isnot(None)).all()
    events = [(r.event, r.result) for r in rows]
    assert ("patient_search", "success") in events
    assert ("ledger_view", "success") in events
    assert ("payment", "success") in events
    assert ("payment", "failure") in events
    pr = next(r for r in rows if r.event == "payment" and r.result == "success")
    assert "125.40" in pr.detail and pr.location_name == "Downtown" and pr.username == "bot_downtown"


def test_automation_user_has_no_admin_access(dt):
    assert dt.get("/api/dev/settings").status_code == 403
    assert dt.get("/api/dev/audit").status_code == 403
    assert dt.post("/api/dev/reset-db").status_code == 403
