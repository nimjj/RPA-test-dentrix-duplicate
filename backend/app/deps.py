"""Request context: client IP, session loading, idle timeout, bot detection."""
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Optional

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from . import botdetect, clock
from .audit import audit
from .db import get_db
from .errors import ApiError, deny
from .models import Location, SessionRow, User
from .runtime_settings import get_settings
from .security import sha256

SESSION_COOKIE = "ledgerlab_session"
DEVICE_COOKIE = "device_id"

IDLE_MESSAGE = "You were logged out due to inactivity"
BOT_MESSAGE = "Your session was ended because of inappropriate usage. Please log in again."
MAINTENANCE_MESSAGE = "LedgerLab is down for scheduled maintenance. Please try again later."


def get_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def maintenance_error() -> ApiError:
    return ApiError(503, "maintenance", MAINTENANCE_MESSAGE, maintenance=True)


@dataclass
class Ctx:
    db: Session
    user: User
    session: SessionRow
    ip: str
    settings: dict[str, Any]

    @property
    def location(self) -> Optional[Location]:
        if self.session.location_id is None:
            return None
        return self.db.get(Location, self.session.location_id)

    def audit(self, event: str, result: str = "success", detail: str = "") -> None:
        audit(
            self.db, event, ip=self.ip, result=result, user=self.user,
            location_id=self.session.location_id, detail=detail,
        )

    def record_form(self) -> None:
        """Call from handlers that are form submissions (search, MFA code, payment...)."""
        if self.settings["bot_detection"] and botdetect.record_form(
            self.session.id, self.settings["bot_min_action_ms"]
        ):
            self.flag_bot("form submissions faster than %d ms apart" % self.settings["bot_min_action_ms"])

    def flag_bot(self, reason: str) -> None:
        end_session(self.db, self.session, "bot_flagged")
        self.user.flagged = True
        self.audit("bot_flag", "failure", reason)
        deny(self.db, 403, "bot_detected", BOT_MESSAGE)


def end_session(db: Session, sess: SessionRow, reason: str) -> None:
    sess.ended_reason = reason
    sess.ended_at = clock.now()
    botdetect.forget(sess.id)


def auth(
    *, states: Optional[tuple[str, ...]] = ("active",), admin: bool = False, need_location: bool = True
) -> Callable[..., Ctx]:
    """Dependency factory. states=None accepts any live session state."""

    def dep(request: Request, db: Session = Depends(get_db)) -> Ctx:
        ip = get_ip(request)
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            raise ApiError(401, "not_authenticated", "Please log in.")
        sess = db.get(SessionRow, sha256(token))
        if sess is None:
            raise ApiError(401, "not_authenticated", "Please log in.")
        if sess.ended_reason == "idle_timeout":
            raise ApiError(401, "idle_timeout", IDLE_MESSAGE)
        if sess.ended_reason == "bot_flagged":
            raise ApiError(401, "bot_detected", BOT_MESSAGE)
        if sess.ended_reason:
            raise ApiError(401, "not_authenticated", "Please log in.")

        user = db.get(User, sess.user_id)
        settings = get_settings(db)
        ctx = Ctx(db=db, user=user, session=sess, ip=ip, settings=settings)

        now = clock.now()
        if now - sess.last_activity > timedelta(minutes=settings["idle_timeout_minutes"]):
            end_session(db, sess, "idle_timeout")
            ctx.audit("timeout", "info", f"idle for more than {settings['idle_timeout_minutes']} minutes")
            deny(db, 401, "idle_timeout", IDLE_MESSAGE)

        if settings["chaos_outage"] and user.role != "admin":
            raise maintenance_error()

        if settings["bot_detection"] and botdetect.record_request(sess.id, settings["bot_max_requests_per_min"]):
            ctx.flag_bot("more than %d requests in a minute" % settings["bot_max_requests_per_min"])

        if admin and user.role != "admin":
            raise ApiError(403, "forbidden", "Administrator access is required.")
        if states is not None and sess.state not in states:
            if sess.state.startswith("pending_mfa"):
                raise ApiError(403, "mfa_required", "Complete multi-factor authentication first.",
                               mfa_step=sess.state.removeprefix("pending_mfa_"))
            raise ApiError(409, "wrong_state", "That step is not available right now.")
        if need_location and sess.location_id is None:
            raise ApiError(409, "location_required", "Choose a location first.")

        sess.last_activity = now
        db.commit()
        return ctx

    return dep
