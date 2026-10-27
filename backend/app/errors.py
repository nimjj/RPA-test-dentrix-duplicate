from typing import Any

from sqlalchemy.orm import Session


class ApiError(Exception):
    """Error rendered as {"code", "message", ...extra} with the given status."""

    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def body(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


def deny(db: Session, status: int, code: str, message: str, **extra: Any) -> None:
    """Commit whatever the handler changed (audit rows, lockout counters) and raise."""
    db.commit()
    raise ApiError(status, code, message, **extra)
