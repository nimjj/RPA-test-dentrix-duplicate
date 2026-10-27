from typing import Optional

from sqlalchemy.orm import Session

from . import clock
from .models import AuditLog, Location, User


def audit(
    db: Session,
    event: str,
    *,
    ip: str,
    result: str = "success",
    user: Optional[User] = None,
    username: str = "",
    location: Optional[Location] = None,
    location_id: Optional[int] = None,
    detail: str = "",
) -> None:
    """Add an audit row to the caller's transaction. The caller commits."""
    loc_name = ""
    if location is not None:
        location_id = location.id
        loc_name = location.name
    elif location_id is not None:
        loc = db.get(Location, location_id)
        loc_name = loc.name if loc else ""
    db.add(
        AuditLog(
            ts=clock.now(),
            event=event,
            user_id=user.id if user else None,
            username=user.username if user else username,
            location_id=location_id,
            location_name=loc_name,
            ip=ip,
            result=result,
            detail=detail,
        )
    )
