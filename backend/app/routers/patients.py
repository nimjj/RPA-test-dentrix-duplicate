import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from .. import clock
from ..deps import Ctx, auth
from ..errors import deny
from ..models import LedgerEntry, Patient, PaymentType
from ..money import fmt_cents, parse_amount_to_cents

router = APIRouter(tags=["patients"])

APPLY_TO = ("todays_visit", "account_balance")


def _balance(db: Session, patient_id: int) -> int:
    return db.query(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).filter(
        LedgerEntry.patient_id == patient_id
    ).scalar()


def _patient_json(db: Session, p: Patient) -> dict[str, Any]:
    g = db.get(Patient, p.guarantor_id) if p.guarantor_id else p
    return {
        "account_no": p.account_no,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "dob": p.dob.isoformat(),
        "guarantor": {
            "account_no": g.account_no,
            "name": f"{g.last_name}, {g.first_name}",
            "is_self": g.id == p.id,
        },
        "balance": fmt_cents(_balance(db, p.id)),
    }


def _get_patient(ctx: Ctx, account_no: str) -> Patient:
    p = (
        ctx.db.query(Patient)
        .filter(func.upper(Patient.account_no) == account_no.strip().upper(),
                Patient.location_id == ctx.session.location_id)
        .first()
    )
    if p is None:  # also hides patients of other locations
        ctx.audit("patient_lookup", "failure", f"{account_no}: not found")
        deny(ctx.db, 404, "patient_not_found", "Patient not found.")
    return p


@router.get("/patients")
def search_patients(q: str = "", ctx: Ctx = Depends(auth())):
    ctx.record_form()
    term = q.strip()
    query = ctx.db.query(Patient).filter(Patient.location_id == ctx.session.location_id)
    if term:
        like = f"%{term.lower()}%"
        parts = [t for t in re.split(r"[,\s]+", term.lower()) if t]
        name_match = [
            or_(func.lower(Patient.first_name).like(f"%{t}%"), func.lower(Patient.last_name).like(f"%{t}%"))
            for t in parts
        ]
        query = query.filter(or_(func.lower(Patient.account_no).like(like), and_(*name_match)))
    rows = query.order_by(Patient.last_name, Patient.first_name).limit(50).all()
    ctx.audit("patient_search", "success", f"q='{term}' -> {len(rows)} result(s)")
    ctx.db.commit()
    return {"results": [_patient_json(ctx.db, p) for p in rows]}


@router.get("/patients/{account_no}")
def get_patient(account_no: str, ctx: Ctx = Depends(auth())):
    p = _get_patient(ctx, account_no)
    return _patient_json(ctx.db, p)


@router.get("/locations/current/payment-types")
def payment_types(ctx: Ctx = Depends(auth())):
    loc = ctx.location
    return {"payment_types": [{"id": t.id, "label": t.label} for t in loc.payment_types]}


def _ledger_rows(db: Session, p: Patient) -> list[dict[str, Any]]:
    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.patient_id == p.id)
        .order_by(LedgerEntry.entry_date, LedgerEntry.id)
        .all()
    )
    running = 0
    rows = []
    for e in entries:
        running += e.amount_cents
        rows.append(
            {
                "id": e.id,
                "date": e.entry_date.isoformat(),
                "type": e.entry_type,
                "payment_type": e.payment_type.label if e.payment_type else "",
                "note": e.note,
                "apply_to": e.apply_to or "",
                "amount": fmt_cents(e.amount_cents),
                "balance": fmt_cents(running),
            }
        )
    rows.reverse()  # newest first
    return rows


@router.get("/patients/{account_no}/ledger")
def ledger(account_no: str, q: str = "", ctx: Ctx = Depends(auth())):
    p = _get_patient(ctx, account_no)
    term = q.strip().lower()
    if term:
        ctx.record_form()
    rows = _ledger_rows(ctx.db, p)
    if term:
        rows = [r for r in rows if term in r["note"].lower()]
    ctx.audit("ledger_view", "success", f"{p.account_no}" + (f" filter='{q.strip()}'" if term else ""))
    ctx.db.commit()
    return {"patient": _patient_json(ctx.db, p), "entries": rows}


class PaymentIn(BaseModel):
    payment_type_id: int
    amount: Any
    payment_date: date
    apply_to: str = "account_balance"
    note: str = ""


@router.post("/patients/{account_no}/payments", status_code=201)
def post_payment(account_no: str, body: PaymentIn, ctx: Ctx = Depends(auth())):
    ctx.record_form()
    p = _get_patient(ctx, account_no)
    loc = ctx.location

    def reject(code: str, message: str, status: int = 422) -> None:
        ctx.audit("payment", "failure", f"{p.account_no}: {message} (amount={body.amount!r})")
        deny(ctx.db, status, code, message)

    try:
        cents = parse_amount_to_cents(body.amount)
    except ValueError as exc:
        reject("invalid_amount", str(exc))
    ptype = ctx.db.get(PaymentType, body.payment_type_id)
    if ptype is None or ptype.location_id != loc.id:
        reject("invalid_payment_type", "Choose a valid payment type for this location.")
    if body.apply_to not in APPLY_TO:
        reject("invalid_apply_to", "Apply to must be 'Today's visit' or 'Account balance'.")
    if len(body.note) > 255:
        reject("note_too_long", "Note can be at most 255 characters.")
    if loc.lock_before_date and body.payment_date < loc.lock_before_date:
        reject(
            "date_locked",
            f"Transactions dated before {loc.lock_before_date.isoformat()} are locked for {loc.name}. "
            "Choose a later payment date.",
        )

    entry = LedgerEntry(
        patient_id=p.id, entry_date=body.payment_date, entry_type="payment", payment_type_id=ptype.id,
        note=body.note, apply_to=body.apply_to, amount_cents=-cents, created_by=ctx.user.username,
        created_at=clock.now(),
    )
    ctx.db.add(entry)
    ctx.db.flush()
    ctx.audit(
        "payment", "success",
        f"{p.account_no} {fmt_cents(cents)} via '{ptype.label}' dated {body.payment_date.isoformat()} "
        f"apply_to={body.apply_to} note='{body.note}'",
    )
    ctx.db.commit()
    return {
        "entry": {"id": entry.id, "amount": fmt_cents(entry.amount_cents)},
        "balance": fmt_cents(_balance(ctx.db, p.id)),
    }
