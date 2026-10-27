"""Synthetic seed data. Deterministic (fixed random seed), no real people."""
import json
import random
from datetime import date, timedelta

from sqlalchemy.orm import Session

from . import clock
from .config import cfg
from .models import (
    LedgerEntry,
    Location,
    Organization,
    Patient,
    PaymentType,
    User,
    UserLocation,
)
from .security import hash_password

DEFAULT_TYPES = [
    ("visa", "Visa"),
    ("mastercard", "Mastercard"),
    ("amex", "Amex"),
    ("discover", "Discover"),
    ("cash", "Cash"),
    ("check", "Check"),
]
# Lakeside renames its types so a bot has to map card types per location.
LAKESIDE_LABELS = {
    "visa": "VISA - Front Desk",
    "mastercard": "MC - Front Desk",
    "amex": "AMEX - Front Desk",
    "discover": "DISC - Front Desk",
    "cash": "Cash Drawer",
    "check": "Check (Deposit)",
}

FIRST_NAMES = [
    "Olivia", "Liam", "Emma", "Noah", "Ava", "Elijah", "Sophia", "Lucas", "Mia", "Mason",
    "Isabella", "Ethan", "Amelia", "Logan", "Harper", "James", "Evelyn", "Aiden", "Abigail", "Jackson",
    "Ella", "Henry", "Scarlett", "Owen", "Grace", "Caleb", "Chloe", "Wyatt", "Lily", "Isaac",
]
LAST_NAMES = [
    "Alvarez", "Bennett", "Carver", "Dawson", "Ellison", "Fischer", "Grant", "Hale", "Iverson", "Jensen",
    "Keller", "Lawson", "Mercer", "Nolan", "Orwell", "Prescott", "Quinn", "Rowan", "Sutton", "Thatcher",
    "Underwood", "Vance", "Whitaker", "Yates", "Zimmer",
]
PROCEDURES = [
    ("Periodic oral evaluation (D0120)", 6500),
    ("Prophylaxis - adult (D1110)", 11500),
    ("Bitewing radiographs, four films (D0274)", 7500),
    ("Resin composite, one surface posterior (D2391)", 21500),
    ("Resin composite, two surfaces posterior (D2392)", 26500),
    ("Crown, porcelain/ceramic (D2740)", 118000),
    ("Scaling and root planing, per quadrant (D4341)", 24000),
    ("Extraction, erupted tooth (D7140)", 19500),
    ("Topical fluoride varnish (D1206)", 4500),
    ("Root canal, molar (D3330)", 109000),
]

# patient index -> guarantor index (families), per location
FAMILIES = {1: 0, 2: 0, 6: 5, 7: 5, 8: 5, 12: 11, 16: 15}


def _users_spec():
    return [
        ("admin", "Alex Admin", "admin", ["Downtown", "Lakeside"]),
        ("frontdesk_downtown", "Dana Frontdesk", "front_desk", ["Downtown"]),
        ("frontdesk_lakeside", "Lee Frontdesk", "front_desk", ["Lakeside"]),
        ("bot_downtown", "Automation Downtown", "automation", ["Downtown"]),
        ("bot_lakeside", "Automation Lakeside", "automation", ["Lakeside"]),
    ]


def seed(db: Session) -> None:
    rng = random.Random(20260101)
    today = clock.today()

    org = Organization(
        name="Sunrise Dental Group",
        slug="sunrise",
        trusted_ips=json.dumps(cfg.default_trusted_ips),
    )
    db.add(org)
    db.flush()

    locs: dict[str, Location] = {}
    for name, prefix in (("Downtown", "DT"), ("Lakeside", "LS")):
        loc = Location(org_id=org.id, name=name, prefix=prefix, lock_before_date=None)
        db.add(loc)
        db.flush()
        locs[name] = loc
        for i, (code, label) in enumerate(DEFAULT_TYPES):
            if name == "Lakeside":
                label = LAKESIDE_LABELS[code]
            db.add(PaymentType(location_id=loc.id, code=code, label=label, sort=i))
    db.flush()

    pw_hash = hash_password(cfg.seed_password)
    for idx, (username, full_name, role, loc_names) in enumerate(_users_spec()):
        user = User(
            org_id=org.id,
            username=username,
            full_name=full_name,
            email=f"{username}@sunrise.test",
            phone=f"+1-555-01{idx:02d}",
            password_hash=pw_hash,
            role=role,
        )
        db.add(user)
        db.flush()
        for ln in loc_names:
            db.add(UserLocation(user_id=user.id, location_id=locs[ln].id))
    db.flush()

    for loc_name, loc in locs.items():
        start = 100220 if loc.prefix == "DT" else 200101
        _seed_patients(db, rng, loc, start, today)
    db.commit()


def _seed_patients(db: Session, rng: random.Random, loc: Location, start: int, today: date) -> None:
    types = db.query(PaymentType).filter(PaymentType.location_id == loc.id).order_by(PaymentType.id).all()
    card_and_other = types
    patients: list[Patient] = []
    names = rng.sample(FIRST_NAMES, 20)
    lasts = rng.sample(LAST_NAMES, 20)
    for i in range(20):
        guarantor_idx = FAMILIES.get(i)
        last = lasts[guarantor_idx] if guarantor_idx is not None else lasts[i]
        is_child = guarantor_idx is not None and i % 2 == 0
        year = rng.randint(2010, 2018) if is_child else rng.randint(1958, 1996)
        p = Patient(
            account_no=f"{loc.prefix}-{start + i}",
            first_name=names[i],
            last_name=last,
            dob=date(year, rng.randint(1, 12), rng.randint(1, 28)),
            location_id=loc.id,
            guarantor_id=None,  # set below once ids exist
        )
        db.add(p)
        db.flush()
        patients.append(p)
    for i, p in enumerate(patients):
        g = FAMILIES.get(i)
        p.guarantor_id = patients[g].id if g is not None else p.id
    db.flush()

    for p in patients:
        _seed_ledger(db, rng, p, card_and_other, today)


def _seed_ledger(db: Session, rng: random.Random, patient: Patient, types: list[PaymentType], today: date) -> None:
    visits = rng.randint(2, 4)
    day = today - timedelta(days=rng.randint(10, 40))
    dates = []
    for _ in range(visits):
        dates.append(day)
        day = day - timedelta(days=rng.randint(60, 150))
    dates.reverse()  # oldest first
    balance = 0
    for vi, d in enumerate(dates):
        for _ in range(rng.randint(1, 2)):
            desc, cents = rng.choice(PROCEDURES)
            db.add(
                LedgerEntry(
                    patient_id=patient.id, entry_date=d, entry_type="charge", note=desc,
                    amount_cents=cents, created_by="seed", created_at=clock.now(),
                )
            )
            balance += cents
        if balance > 30000 and rng.random() < 0.5:
            adj = rng.choice([2500, 5000, 10000])
            db.add(
                LedgerEntry(
                    patient_id=patient.id, entry_date=d, entry_type="adjustment",
                    note="Insurance write-off", amount_cents=-adj, created_by="seed", created_at=clock.now(),
                )
            )
            balance -= adj
        last_visit = vi == len(dates) - 1
        # Most older balances get paid; the newest visit is often left (partly) open.
        if not last_visit or rng.random() < 0.4:
            pay = balance if (not last_visit or rng.random() < 0.5) else max(balance // 2, 100)
            pay = max(min(pay, balance), 0)
            if pay > 0:
                pt = rng.choice(types)
                db.add(
                    LedgerEntry(
                        patient_id=patient.id, entry_date=d, entry_type="payment", payment_type_id=pt.id,
                        note=f"Paid at visit - POS txn {rng.randint(100000, 999999)}",
                        apply_to="todays_visit", amount_cents=-pay, created_by="seed", created_at=clock.now(),
                    )
                )
                balance -= pay
