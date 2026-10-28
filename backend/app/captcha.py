"""reCAPTCHA Enterprise verification (checkbox key) and the 'is a CAPTCHA needed' rule."""
import logging

import httpx

from .config import cfg

log = logging.getLogger("ledgerlab.captcha")

ASSESSMENT_URL = "https://recaptchaenterprise.googleapis.com/v1/projects/{project}/assessments"
SITEVERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
# Official Google reCAPTCHA test keys for localhost / automated testing
GOOGLE_TEST_SITE_KEY = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
GOOGLE_TEST_SECRET_KEY = "6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe"


def active_site_key() -> str:
    if cfg.recaptcha_site_key:
        return cfg.recaptcha_site_key
    if cfg.captcha_provider == "test":
        return GOOGLE_TEST_SITE_KEY
    return ""


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
    """Create an assessment (enterprise) or siteverify check (test) and return whether the token is valid."""
    if not token:
        return False
    if cfg.captcha_provider == "test":
        try:
            resp = httpx.post(
                SITEVERIFY_URL,
                data={"secret": GOOGLE_TEST_SECRET_KEY, "response": token},
                timeout=10,
            )
            resp.raise_for_status()
            return bool(resp.json().get("success"))
        except Exception:
            log.exception("reCAPTCHA test siteverify failed")
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
