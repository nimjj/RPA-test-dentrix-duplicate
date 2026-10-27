"""reCAPTCHA Enterprise verification (checkbox key) and the 'is a CAPTCHA needed' rule."""
import logging

import httpx

from .config import cfg

log = logging.getLogger("ledgerlab.captcha")

ASSESSMENT_URL = "https://recaptchaenterprise.googleapis.com/v1/projects/{project}/assessments"


def captcha_required(*, mode: str, device_recognized: bool, flagged: bool) -> bool:
    if cfg.captcha_provider == "off":
        return False
    if flagged:  # bot detection flag forces a CAPTCHA at the next login in every mode
        return True
    if mode == "never":
        return False
    if mode == "always":
        return True
    if mode == "new_device":
        return not device_recognized
    return False  # after_flag: only flagged accounts, handled above


def verify_token(token: str) -> bool:
    """Create an assessment and accept only when tokenProperties.valid is true."""
    if not token:
        return False
    if not (cfg.recaptcha_project_id and cfg.recaptcha_site_key and cfg.recaptcha_api_key):
        log.error("CAPTCHA_PROVIDER=enterprise but RECAPTCHA_* values are missing")
        return False
    url = ASSESSMENT_URL.format(project=cfg.recaptcha_project_id)
    try:
        resp = httpx.post(
            url,
            params={"key": cfg.recaptcha_api_key},
            json={"event": {"token": token, "siteKey": cfg.recaptcha_site_key}},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.exception("reCAPTCHA Enterprise assessment failed")
        return False
    return bool(data.get("tokenProperties", {}).get("valid"))
