from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import clock
from ..audit import audit
from ..captcha import captcha_required, verify_token
from ..config import cfg
from ..db import get_db
from ..deps import (
    DEVICE_COOKIE,
    SESSION_COOKIE,
    Ctx,
    auth,
    end_session,
    get_ip,
    maintenance_error,
)
from ..errors import ApiError, deny
from ..mail import send_email
from ..models import (
    Device,
    Location,
    MfaChallenge,
    Organization,
    SessionRow,
    SmsMessage,
    User,
)
from ..runtime_settings import get_settings
from ..security import ip_is_trusted, new_code, new_token, sha256, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

MFA_CODE_MINUTES = 10
MFA_MAX_ATTEMPTS = 5
LOCK_MINUTES = 5
MAX_FAILED = 5


# ---------------------------------------------------------------- helpers
def _find_org(db: Session, text: str) -> Optional[Organization]:
    t = text.strip().lower()
    if not t:
        return None
    return (
        db.query(Organization)
        .filter(func.lower(Organization.slug) == t)
        .first()
        or db.query(Organization).filter(func.lower(Organization.name) == t).first()
    )


def _find_user(db: Session, org: Optional[Organization], username: str) -> Optional[User]:
    if org is None:
        return None
    return (
        db.query(User)
        .filter(User.org_id == org.id, func.lower(User.username) == username.strip().lower())
        .first()
    )


def _device_recognized(db: Session, user: Optional[User], cookie: Optional[str]) -> bool:
    if user is None or not cookie:
        return False
    return (
        db.query(Device).filter(Device.user_id == user.id, Device.token_hash == sha256(cookie)).first()
        is not None
    )


def _set_cookie(response: Response, name: str, value: str, max_age: Optional[int] = None) -> None:
    response.set_cookie(
        name, value, httponly=True, samesite="lax", secure=cfg.cookie_secure, max_age=max_age, path="/"
    )


def _next_step(sess: SessionRow) -> dict:
    if sess.state.startswith("pending_mfa"):
        return {"next": "mfa", "mfa_step": sess.state.removeprefix("pending_mfa_")}
    if sess.location_id is None:
        return {"next": "location"}
    return {"next": "app"}


def _issue_challenge(db: Session, ctx_user: User, sess: SessionRow, step: str, ip: str) -> None:
    """Invalidate older codes for this step, create a new one and deliver it."""
    for old in db.query(MfaChallenge).filter(
        MfaChallenge.session_id == sess.id, MfaChallenge.step == step, MfaChallenge.consumed.is_(False)
    ):
        old.consumed = True
    code = new_code()
    now = clock.now()
    db.add(
        MfaChallenge(
            session_id=sess.id, step=step, code_hash=sha256(code), created_at=now,
            expires_at=now + timedelta(minutes=MFA_CODE_MINUTES),
        )
    )
    if step == "email":
        send_email(
            ctx_user.email,
            "Your LedgerLab verification code",
            f"Your verification code is {code}. It expires in {MFA_CODE_MINUTES} minutes.",
        )
    else:
        db.add(
            SmsMessage(
                user_id=ctx_user.id, username=ctx_user.username, phone=ctx_user.phone, code=code, created_at=now
            )
        )
    audit(db, "mfa_sent", ip=ip, user=ctx_user, location_id=sess.location_id, detail=f"{step} code sent")


def _activate(db: Session, sess: SessionRow, user: User) -> None:
    sess.state = "active"
    user.flagged = False  # a completed login (with CAPTCHA/MFA when forced) clears the bot flag


# ---------------------------------------------------------------- identify
class IdentifyIn(BaseModel):
    organization: str
    username: str


@router.post("/identify")
def identify(body: IdentifyIn, request: Request, db: Session = Depends(get_db)):
    """Screen 1. Never reveals whether the organization or user exists."""
    ip = get_ip(request)
    settings = get_settings(db)
    org = _find_org(db, body.organization)
    user = _find_user(db, org, body.username)
    if settings["chaos_outage"] and not (user and user.role == "admin"):
        raise maintenance_error()
    recognized = _device_recognized(db, user, request.cookies.get(DEVICE_COOKIE))
    required = captcha_required(
        mode=settings["captcha_mode"], device_recognized=recognized, flagged=bool(user and user.flagged)
    )
    if required:
        audit(db, "captcha_shown", ip=ip, user=user, username=body.username.strip(), result="info",
              detail=f"mode={settings['captcha_mode']}")
        db.commit()
    return {
        "ok": True,
        "captcha_required": required,
        "captcha_provider": cfg.captcha_provider,
        "site_key": cfg.recaptcha_site_key if required else "",
    }


# ---------------------------------------------------------------- login
class LoginIn(BaseModel):
    organization: str
    username: str
    password: str
    captcha_token: Optional[str] = None


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = get_ip(request)
    settings = get_settings(db)
    org = _find_org(db, body.organization)
    user = _find_user(db, org, body.username)
    uname = body.username.strip()

    if settings["chaos_outage"] and not (user and user.role == "admin"):
        raise maintenance_error()

    device_cookie = request.cookies.get(DEVICE_COOKIE)
    recognized = _device_recognized(db, user, device_cookie)
    need_captcha = captcha_required(
        mode=settings["captcha_mode"], device_recognized=recognized, flagged=bool(user and user.flagged)
    )

    # The CAPTCHA is verified before the password is looked at.
    if need_captcha:
        if not body.captcha_token or not verify_token(body.captcha_token):
            audit(db, "captcha_failed", ip=ip, user=user, username=uname, result="failure")
            audit(db, "login_attempt", ip=ip, user=user, username=uname, result="failure", detail="captcha failed")
            deny(db, 400, "captcha_failed", "CAPTCHA verification failed. Please try again.")
        audit(db, "captcha_passed", ip=ip, user=user, username=uname)

    if user is None:
        audit(db, "login_attempt", ip=ip, username=uname, result="failure", detail="unknown organization or user")
        deny(db, 401, "invalid_credentials", "Invalid organization, username or password.")

    now = clock.now()
    if user.status == "blocked":
        audit(db, "login_attempt", ip=ip, user=user, result="failure", detail="account blocked")
        deny(db, 403, "account_blocked",
             "This account is blocked. Contact an administrator to reactivate it.")
    if user.locked_until and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        audit(db, "login_attempt", ip=ip, user=user, result="failure", detail="account locked")
        deny(db, 423, "account_locked",
             f"This account is temporarily locked. Try again in {minutes} minute(s).",
             retry_after_seconds=int((user.locked_until - now).total_seconds()))

    if not verify_password(body.password, user.password_hash):
        user.failed_count += 1
        audit(db, "login_attempt", ip=ip, user=user, result="failure",
              detail=f"wrong password ({user.failed_count}/{MAX_FAILED})")
        if user.failed_count >= MAX_FAILED:
            user.failed_count = 0
            if user.lock_stage == 0:
                user.lock_stage = 1
                user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                audit(db, "lockout", ip=ip, user=user, result="failure",
                      detail=f"locked for {LOCK_MINUTES} minutes after {MAX_FAILED} wrong passwords")
                deny(db, 423, "account_locked",
                     f"Too many failed attempts. The account is locked for {LOCK_MINUTES} minutes.",
                     retry_after_seconds=LOCK_MINUTES * 60)
            user.status = "blocked"
            user.locked_until = None
            audit(db, "account_blocked", ip=ip, user=user, result="failure",
                  detail=f"blocked after {MAX_FAILED} more wrong passwords; admin must reactivate")
            deny(db, 403, "account_blocked",
                 "This account is blocked. Contact an administrator to reactivate it.")
        deny(db, 401, "invalid_credentials", "Invalid organization, username or password.")

    # Password OK
    user.failed_count = 0
    user.lock_stage = 0
    user.locked_until = None

    mfa_required = (not recognized and not ip_is_trusted(ip, org)) or (
        user.flagged and settings["bot_flag_forces_mfa"]
    )
    token = new_token()
    sess = SessionRow(
        id=sha256(token), user_id=user.id, state="pending_mfa_email" if mfa_required else "active",
        location_id=user.locations[0].id if len(user.locations) == 1 else None,
        created_at=now, last_activity=now, ip=ip,
    )
    db.add(sess)
    db.flush()
    audit(db, "login_attempt", ip=ip, user=user, location_id=sess.location_id,
          detail="password accepted, MFA required" if mfa_required else "password accepted")
    if mfa_required:
        _issue_challenge(db, user, sess, "email", ip)
    else:
        _activate(db, sess, user)
    db.commit()
    _set_cookie(response, SESSION_COOKIE, token)
    return _next_step(sess)


# ---------------------------------------------------------------- MFA
class CodeIn(BaseModel):
    code: str


def _check_code(ctx: Ctx, step: str, code: str) -> None:
    db = ctx.db
    ch = (
        db.query(MfaChallenge)
        .filter(MfaChallenge.session_id == ctx.session.id, MfaChallenge.step == step,
                MfaChallenge.consumed.is_(False))
        .order_by(MfaChallenge.id.desc())
        .first()
    )
    if ch is None or ch.expires_at < clock.now():
        ctx.audit("mfa_failed", "failure", f"{step} code expired or missing")
        deny(db, 400, "code_expired", "That code has expired. Request a new one.")
    if sha256(code.strip()) != ch.code_hash:
        ch.attempts += 1
        ctx.audit("mfa_failed", "failure", f"{step} wrong code ({ch.attempts}/{MFA_MAX_ATTEMPTS})")
        if ch.attempts >= MFA_MAX_ATTEMPTS:
            ch.consumed = True
            end_session(db, ctx.session, "mfa_failed")
            deny(db, 401, "mfa_failed", "Too many wrong codes. Please log in again.")
        deny(db, 400, "invalid_code", "That code is not correct.")
    ch.consumed = True
    ctx.audit("mfa_passed", "success", f"{step} code accepted")


def _finish_mfa(ctx: Ctx, request: Request, response: Response) -> dict:
    db, user = ctx.db, ctx.user
    now = clock.now()
    cookie = request.cookies.get(DEVICE_COOKIE)
    if not cookie:
        cookie = new_token()
    dev = db.query(Device).filter(Device.user_id == user.id, Device.token_hash == sha256(cookie)).first()
    if dev is None:
        db.add(Device(user_id=user.id, token_hash=sha256(cookie), created_at=now, last_seen_at=now))
    else:
        dev.last_seen_at = now
    _activate(db, ctx.session, user)
    db.commit()
    _set_cookie(response, DEVICE_COOKIE, cookie, max_age=90 * 24 * 3600)
    return _next_step(ctx.session)


@router.post("/mfa/email")
def mfa_email(
    body: CodeIn, request: Request, response: Response,
    ctx: Ctx = Depends(auth(states=("pending_mfa_email",), need_location=False)),
):
    ctx.record_form()
    _check_code(ctx, "email", body.code)
    if ctx.settings["mfa_sms_step"]:
        ctx.session.state = "pending_mfa_sms"
        _issue_challenge(ctx.db, ctx.user, ctx.session, "sms", ctx.ip)
        ctx.db.commit()
        return _next_step(ctx.session)
    return _finish_mfa(ctx, request, response)


@router.post("/mfa/sms")
def mfa_sms(
    body: CodeIn, request: Request, response: Response,
    ctx: Ctx = Depends(auth(states=("pending_mfa_sms",), need_location=False)),
):
    ctx.record_form()
    _check_code(ctx, "sms", body.code)
    return _finish_mfa(ctx, request, response)


@router.post("/mfa/resend")
def mfa_resend(
    ctx: Ctx = Depends(auth(states=("pending_mfa_email", "pending_mfa_sms"), need_location=False)),
):
    step = ctx.session.state.removeprefix("pending_mfa_")
    _issue_challenge(ctx.db, ctx.user, ctx.session, step, ctx.ip)
    ctx.db.commit()
    return {"ok": True, "mfa_step": step}


# ---------------------------------------------------------------- location / me / logout
class LocationIn(BaseModel):
    location_id: int


@router.post("/location")
def choose_location(body: LocationIn, ctx: Ctx = Depends(auth(need_location=False))):
    ctx.record_form()
    loc = next((l for l in ctx.user.locations if l.id == body.location_id), None)
    if loc is None:
        raise ApiError(403, "forbidden", "You do not have access to that location.")
    ctx.session.location_id = loc.id
    ctx.audit("location_selected", "success", loc.name)
    ctx.db.commit()
    return {"next": "app"}


@router.get("/me")
def me(ctx: Ctx = Depends(auth(states=None, need_location=False))):
    u = ctx.user
    loc = ctx.location
    return {
        "state": ctx.session.state,
        "user": {"username": u.username, "full_name": u.full_name, "role": u.role},
        "organization": {"name": u.org.name},
        "location": {"id": loc.id, "name": loc.name} if loc else None,
        "locations": [{"id": l.id, "name": l.name} for l in u.locations],
        **_next_step(ctx.session),
    }


@router.post("/logout")
def logout(response: Response, ctx: Ctx = Depends(auth(states=None, need_location=False))):
    end_session(ctx.db, ctx.session, "logout")
    ctx.audit("logout", "success")
    ctx.db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
