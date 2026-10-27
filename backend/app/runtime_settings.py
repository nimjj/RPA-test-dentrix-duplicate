"""Settings the Dev Settings page changes at runtime, stored in the `setting`
table and read on every request, so no restart is needed."""
import json
from typing import Any

from sqlalchemy.orm import Session

from .config import cfg
from .models import SettingRow

CAPTCHA_MODES = ("never", "new_device", "after_flag", "always")

# key -> (type, min, max)
SPEC: dict[str, tuple] = {
    "captcha_mode": ("choice", CAPTCHA_MODES),
    "mfa_sms_step": ("bool",),
    "idle_timeout_minutes": ("int", 1, 1440),
    "bot_detection": ("bool",),
    "bot_max_requests_per_min": ("int", 1, 100000),
    "bot_min_action_ms": ("int", 0, 60000),
    "bot_flag_forces_mfa": ("bool",),
    "chaos_slow": ("bool",),
    "chaos_outage": ("bool",),
    "chaos_ui_changed": ("bool",),
}


def get_settings(db: Session) -> dict[str, Any]:
    values = dict(cfg.default_settings)
    for row in db.query(SettingRow).all():
        if row.key in SPEC:
            try:
                values[row.key] = json.loads(row.value)
            except ValueError:
                pass
    if values["captcha_mode"] not in CAPTCHA_MODES:
        values["captcha_mode"] = "new_device"
    return values


def validate_value(key: str, value: Any) -> Any:
    """Return the cleaned value or raise ValueError with a readable message."""
    if key not in SPEC:
        raise ValueError(f"Unknown setting '{key}'.")
    spec = SPEC[key]
    kind = spec[0]
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"'{key}' must be true or false.")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"'{key}' must be a whole number.")
        if not (spec[1] <= value <= spec[2]):
            raise ValueError(f"'{key}' must be between {spec[1]} and {spec[2]}.")
        return value
    if kind == "choice":
        if value not in spec[1]:
            raise ValueError(f"'{key}' must be one of: {', '.join(spec[1])}.")
        return value
    raise ValueError("Bad setting spec.")  # pragma: no cover


def set_setting(db: Session, key: str, value: Any) -> None:
    clean = validate_value(key, value)
    row = db.get(SettingRow, key)
    if row is None:
        db.add(SettingRow(key=key, value=json.dumps(clean)))
    else:
        row.value = json.dumps(clean)
