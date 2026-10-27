import json
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import clock
from ..config import cfg
from ..db import get_db, reset_db
from ..deps import Ctx, auth
from ..errors import ApiError
from ..models import AuditLog, Device, Location, Organization, PaymentType, SmsMessage, User
from ..runtime_settings import get_settings, set_setting
from ..security import get_trusted_ips, normalize_ip_list

router = APIRouter(prefix="/dev", tags=["dev"])

admin = auth(admin=True, need_location=False)


# ------------------------------------------------------------------ SMS inbox (open on purpose)
def _sms_json(m: SmsMessage) -> dict[str, Any]:
    return {
        "id": m.id, "user": m.username, "phone": m.phone, "code": m.code,
        "created_at": m.created_at.isoformat() + "Z",
    }


@router.get("/sms/latest")
def sms_latest(user: str, db: Session = Depends(get_db)):
    """Latest 'SMS' for a username, so a bot can read the second MFA code."""
    m = (
        db.query(SmsMessage)
        .filter(SmsMessage.username == user)
        .order_by(SmsMessage.id.desc())
        .first()
    )
    if m is None:
        raise ApiError(404, "no_sms", f"No SMS has been sent to '{user}'.")
    return _sms_json(m)


@router.get("/sms")
def sms_list(user: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(SmsMessage)
    if user:
        q = q.filter(SmsMessage.username == user)
    return {"messages": [_sms_json(m) for m in q.order_by(SmsMessage.id.desc()).limit(100)]}


# ------------------------------------------------------------------ settings
def _users_json(db: Session) -> list[dict[str, Any]]:
    now = clock.now()
    out = []
    for u in db.query(User).order_by(User.id):
        locked = bool(u.locked_until and u.locked_until > now)
        out.append(
            {
                "id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role,
                "email": u.email,
                "status": "blocked" if u.status == "blocked" else ("locked" if locked else "active"),
                "locked_until": u.locked_until.isoformat() + "Z" if locked else None,
                "flagged": u.flagged,
                "devices": db.query(Device).filter(Device.user_id == u.id).count(),
                "locations": [l.name for l in u.locations],
            }
        )
    return out


def _settings_payload(db: Session) -> dict[str, Any]:
    org = db.query(Organization).first()
    return {
        "settings": get_settings(db),
        "captcha_provider": cfg.captcha_provider,
        "organization": {"name": org.name, "trusted_ips": get_trusted_ips(org)},
        "locations": [
            {
                "id": l.id, "name": l.name,
                "lock_before_date": l.lock_before_date.isoformat() if l.lock_before_date else None,
                "payment_types": [{"id": t.id, "code": t.code, "label": t.label} for t in l.payment_types],
            }
            for l in db.query(Location).order_by(Location.id)
        ],
        "users": _users_json(db),
    }


@router.get("/settings")
def read_settings(ctx: Ctx = Depends(admin)):
    return _settings_payload(ctx.db)


@router.put("/settings")
def update_settings(body: dict[str, Any], ctx: Ctx = Depends(admin)):
    changes = []
    for key, value in body.items():
        try:
            set_setting(ctx.db, key, value)
        except ValueError as exc:
            ctx.db.rollback()
            raise ApiError(422, "invalid_setting", str(exc))
        changes.append(f"{key}={json.dumps(value)}")
    ctx.audit("settings_change", "success", ", ".join(changes))
    ctx.db.commit()
    return _settings_payload(ctx.db)


class TrustedIpsIn(BaseModel):
    ips: list[str]


@router.put("/org/trusted-ips")
def update_trusted_ips(body: TrustedIpsIn, ctx: Ctx = Depends(admin)):
    try:
        ips = normalize_ip_list(body.ips)
    except ValueError as exc:
        raise ApiError(422, "invalid_ip", f"Not a valid IP address or CIDR range: {exc}")
    org = ctx.user.org
    org.trusted_ips = json.dumps(ips)
    ctx.audit("settings_change", "success", f"trusted_ips={ips}")
    ctx.db.commit()
    return _settings_payload(ctx.db)


class PaymentTypeLabel(BaseModel):
    id: int
    label: str


class LocationIn(BaseModel):
    lock_before_date: Optional[date] = None
    payment_types: Optional[list[PaymentTypeLabel]] = None


@router.put("/locations/{location_id}")
def update_location(location_id: int, body: LocationIn, ctx: Ctx = Depends(admin)):
    loc = ctx.db.get(Location, location_id)
    if loc is None:
        raise ApiError(404, "not_found", "Location not found.")
    fields = body.model_fields_set
    notes = []
    if "lock_before_date" in fields:
        loc.lock_before_date = body.lock_before_date
        notes.append(f"lock_before_date={body.lock_before_date}")
    if body.payment_types is not None:
        by_id = {t.id: t for t in loc.payment_types}
        for item in body.payment_types:
            t = by_id.get(item.id)
            label = item.label.strip()
            if t is None or not label or len(label) > 60:
                raise ApiError(422, "invalid_payment_type", "Payment type labels must be 1-60 characters.")
            t.label = label
        notes.append("payment type labels updated")
    ctx.audit("settings_change", "success", f"{loc.name}: " + ", ".join(notes))
    ctx.db.commit()
    return _settings_payload(ctx.db)


# ------------------------------------------------------------------ users
def _user_or_404(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise ApiError(404, "not_found", "User not found.")
    return u


@router.get("/users")
def list_users(ctx: Ctx = Depends(admin)):
    return {"users": _users_json(ctx.db)}


@router.post("/users/{user_id}/reactivate")
def reactivate(user_id: int, ctx: Ctx = Depends(admin)):
    u = _user_or_404(ctx.db, user_id)
    u.status = "active"
    u.failed_count = 0
    u.lock_stage = 0
    u.locked_until = None
    ctx.audit("user_reactivated", "success", u.username)
    ctx.db.commit()
    return {"users": _users_json(ctx.db)}


@router.post("/users/{user_id}/clear-devices")
def clear_devices(user_id: int, ctx: Ctx = Depends(admin)):
    u = _user_or_404(ctx.db, user_id)
    n = ctx.db.query(Device).filter(Device.user_id == u.id).delete()
    ctx.audit("devices_cleared", "success", f"{u.username}: {n} device(s)")
    ctx.db.commit()
    return {"users": _users_json(ctx.db)}


@router.post("/reset-db")
def reset_database(ctx: Ctx = Depends(admin)):
    reset_db()
    return {"ok": True, "message": "Database reset to seed data. Log in again."}


# ------------------------------------------------------------------ audit log
def _audit_json(a: AuditLog) -> dict[str, Any]:
    return {
        "id": a.id, "time": a.ts.isoformat() + "Z", "event": a.event, "user": a.username,
        "location": a.location_name, "ip": a.ip, "result": a.result, "detail": a.detail,
    }


@router.get("/audit")
def audit_log(
    event: Optional[str] = None,
    user: Optional[str] = None,
    result: Optional[str] = None,
    location: Optional[str] = None,
    q: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
    ctx: Ctx = Depends(admin),
):
    query = ctx.db.query(AuditLog)
    if event:
        query = query.filter(AuditLog.event == event)
    if user:
        query = query.filter(AuditLog.username == user)
    if result:
        query = query.filter(AuditLog.result == result)
    if location:
        query = query.filter(AuditLog.location_name == location)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(AuditLog.detail.like(like), AuditLog.username.like(like), AuditLog.ip.like(like)))
    if since:
        query = query.filter(AuditLog.ts >= since)
    if until:
        query = query.filter(AuditLog.ts <= until)
    total = query.count()
    rows = query.order_by(AuditLog.id.desc()).offset(max(offset, 0)).limit(min(max(limit, 1), 500)).all()
    events = [e for (e,) in ctx.db.query(AuditLog.event).distinct().order_by(AuditLog.event)]
    return {"total": total, "events": events, "rows": [_audit_json(a) for a in rows]}
