"""Playwright RPA helpers for LedgerLab:
- reCAPTCHA checkbox solver (auto-clicks in test/low-risk mode, or pauses for human in headed mode)
- Mailpit REST API reader for Step 1 Email MFA codes
- Dev SMS Inbox API reader for Step 2 SMS MFA codes
- Rate-limit-aware form submission pacing (respects BOT_MIN_ACTION_MS = 400ms)
- Location-aware card type mapper (Downtown vs. Lakeside renamed payment types)
"""
from __future__ import annotations

import re
import time
from collections import deque
from pathlib import Path
from typing import Optional

import httpx
from playwright.sync_api import BrowserContext, Page, Request, expect

# Minimum delay between consecutive form submissions so we never trip
# BOT_MIN_ACTION_MS (400 ms default in LedgerLab bot detection).
FORM_PACE_SEC = 0.55

# Stay safely below BOT_MAX_REQUESTS_PER_MIN (60 requests / 60s per session)
SAFE_REQUESTS_PER_MIN = 45


class SessionRateGuard:
    """Tracks `/api/` requests in a 60-second sliding window for the current session
    so the RPA bot stays below LedgerLab's `BOT_MAX_REQUESTS_PER_MIN` threshold."""

    def __init__(self, page: Page, max_per_min: int = SAFE_REQUESTS_PER_MIN) -> None:
        self.page = page
        self.max_per_min = max_per_min
        self.timestamps: deque[float] = deque()
        page.on("request", self._on_request)

    def _on_request(self, req: Request) -> None:
        if "/api/" in req.url and not any(x in req.url for x in ("/api/health", "/api/public-config", "/api/dev/")):
            now = time.monotonic()
            self.timestamps.append(now)
            self._prune(now)

    def _prune(self, now: float) -> None:
        while self.timestamps and now - self.timestamps[0] > 60.0:
            self.timestamps.popleft()

    def reset_counter(self) -> None:
        self.timestamps.clear()

    def needs_session_refresh(self) -> bool:
        self._prune(time.monotonic())
        return len(self.timestamps) >= self.max_per_min

CARD_CODE_KEYWORDS = {
    "visa": ["visa"],
    "mastercard": ["mastercard", "mc "],
    "amex": ["amex", "american express"],
    "discover": ["discover", "disc "],
    "cash": ["cash"],
    "check": ["check"],
}


def pace(seconds: float = FORM_PACE_SEC) -> None:
    """Wait between form submissions to stay safely above BOT_MIN_ACTION_MS."""
    time.sleep(seconds)


def fetch_email_mfa_code(
    username: str,
    mailpit_url: str = "http://localhost:8025",
    timeout_sec: float = 10.0,
) -> str:
    """Fetch the newest 6-digit MFA email code for `<username>@sunrise.test` from Mailpit."""
    target = f"{username.lower()}@sunrise.test"
    deadline = time.time() + timeout_sec
    with httpx.Client(timeout=5.0) as client:
        while time.time() < deadline:
            resp = client.get(f"{mailpit_url}/api/v1/messages")
            resp.raise_for_status()
            messages = resp.json().get("messages", [])
            for msg in messages:
                recipients = [r.get("Address", "").lower() for r in msg.get("To", [])]
                if target in recipients:
                    msg_id = msg["ID"]
                    detail = client.get(f"{mailpit_url}/api/v1/message/{msg_id}").json()
                    body = detail.get("Text", "") or detail.get("Snippet", "")
                    m = re.search(r"\b(\d{6})\b", body)
                    if m:
                        return m.group(1)
            time.sleep(0.4)
    raise RuntimeError(f"Timed out waiting for MFA email for {target} in Mailpit ({mailpit_url})")


def fetch_sms_mfa_code(
    username: str,
    app_url: str = "http://localhost:8080",
    timeout_sec: float = 10.0,
) -> str:
    """Fetch the newest 6-digit SMS MFA code for `username` from `/api/dev/sms/latest`."""
    deadline = time.time() + timeout_sec
    with httpx.Client(timeout=5.0) as client:
        while time.time() < deadline:
            resp = client.get(f"{app_url}/api/dev/sms/latest", params={"user": username})
            if resp.status_code == 200:
                code = resp.json().get("code", "")
                if re.fullmatch(r"\d{6}", code):
                    return code
            time.sleep(0.3)
    raise RuntimeError(f"Timed out waiting for SMS MFA code for {username}")


def solve_recaptcha_if_present(page: Page, interactive_timeout_ms: int = 120_000) -> bool:
    """Detect if the reCAPTCHA widget is rendered on Login Screen 2 and complete it.

    Returns True if a CAPTCHA was present and solved, or False if no CAPTCHA was required.
    """
    captcha_container = page.locator(".captcha")
    if captcha_container.count() == 0 or not captcha_container.is_visible():
        return False

    # Wait for Google's reCAPTCHA anchor iframe to load inside .captcha
    iframe_loc = page.locator('.captcha iframe[title="reCAPTCHA"], .captcha iframe[src*="recaptcha/enterprise/anchor"]')
    iframe_loc.first.wait_for(state="visible", timeout=15_000)

    anchor_frame = page.frame_locator('.captcha iframe[title="reCAPTCHA"], .captcha iframe[src*="recaptcha/enterprise/anchor"]').first
    checkbox = anchor_frame.locator("#recaptcha-anchor")
    checkbox.wait_for(state="visible", timeout=15_000)
    checkbox.click()

    # Check if the checkbox immediately turned green (test keys or low-risk score)
    try:
        expect(checkbox).to_have_attribute("aria-checked", "true", timeout=5_000)
        return True
    except AssertionError:
        # If an image challenge opened (e.g. real Enterprise key with challenge),
        # wait for a human operator in headed mode to solve it.
        print("\n[RPA] reCAPTCHA challenge requires human interaction. Please complete the challenge in the browser window...")
        expect(checkbox).to_have_attribute("aria-checked", "true", timeout=interactive_timeout_ms)
        return True


def login_bot(
    context: BrowserContext,
    page: Page,
    username: str,
    password: str = "LedgerLab!2026",
    organization: str = "sunrise",
    app_url: str = "http://localhost:8080",
    mailpit_url: str = "http://localhost:8025",
    state_path: Optional[Path] = None,
) -> dict:
    """Execute the full LedgerLab login flow (Screen 1 -> Screen 2 + CAPTCHA -> Email & SMS MFA).

    Returns a dictionary summarizing whether CAPTCHA and MFA were triggered.
    """
    page.goto(f"{app_url}/login")

    # Screen 1: Organization + Username (compatible with both normal and UI-changed chaos mode)
    org_input = page.get_by_label(re.compile(r"^(Organization|Practice group)$", re.I))
    user_input = page.get_by_label(re.compile(r"^(Username|User ID)$", re.I))
    org_input.fill(organization)
    user_input.fill(username)
    pace()
    page.get_by_role("button", name=re.compile(r"^(Continue|Next)$", re.I)).click()

    # Screen 2: Password + optional reCAPTCHA
    pw_input = page.get_by_label(re.compile(r"^(Password|Passcode)$", re.I))
    pw_input.wait_for(state="visible", timeout=10_000)
    pw_input.fill(password)

    # Give the DOM a moment to mount .captcha if captcha_required=true
    page.wait_for_timeout(300)
    captcha_solved = solve_recaptcha_if_present(page)

    login_btn = page.get_by_role("button", name=re.compile(r"^(Log In|Sign In)$", re.I))
    expect(login_btn).to_be_enabled(timeout=10_000)
    pace()
    login_btn.click()

    # Wait for navigation to either /login/mfa, /select-location, or /patients
    page.wait_for_url(re.compile(r"/(login/mfa|select-location|patients)"), timeout=15_000)

    mfa_completed = False
    if "/login/mfa" in page.url:
        mfa_completed = True
        # Step 1: Email MFA
        email_label = page.get_by_label("Email code")
        email_label.wait_for(state="visible", timeout=10_000)
        email_code = fetch_email_mfa_code(username, mailpit_url=mailpit_url)
        email_label.fill(email_code)
        pace()
        page.get_by_role("button", name="Verify").click()

        # Either moves to Step 2 (Text message code) or navigates away
        page.wait_for_timeout(400)
        sms_label = page.get_by_label("Text message code")
        if "/login/mfa" in page.url and sms_label.is_visible():
            sms_code = fetch_sms_mfa_code(username, app_url=app_url)
            sms_label.fill(sms_code)
            pace()
            page.get_by_role("button", name="Verify").click()

    page.wait_for_url(re.compile(r"/(select-location|patients)"), timeout=15_000)

    if state_path is not None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_path))

    return {
        "username": username,
        "captcha_solved": captcha_solved,
        "mfa_completed": mfa_completed,
    }


def select_Matching_payment_type(select_locator, card_type: str) -> str:
    """Match a canonical card_type (e.g. 'Visa', 'Mastercard') to the location's dropdown label."""
    key = card_type.strip().lower()
    keywords = CARD_CODE_KEYWORDS.get(key, [key])
    options = select_locator.locator("option").all()
    for opt in options:
        label = (opt.inner_text() or "").strip()
        val = opt.get_attribute("value") or ""
        if not val:
            continue
        label_lower = label.lower()
        if any(kw in label_lower for kw in keywords):
            select_locator.select_option(value=val)
            return label
    raise ValueError(f"Could not map card_type '{card_type}' to any option in dropdown")
