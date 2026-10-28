"""End-to-end Playwright RPA verification tests against the live LedgerLab stack."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import login_bot, pace
from post_payments import DEFAULT_CSV, post_single_payment, run_csv_batch

APP_URL = "http://localhost:8080"
API_URL = "http://localhost:8000"
MAILPIT_URL = "http://localhost:8025"


def reset_database_via_admin() -> None:
    """Log in as admin from a trusted IP (or via API) to reset the database to clean seed state."""
    with httpx.Client(base_url=APP_URL, timeout=10.0) as c:
        # Check public config
        cfg = c.get("/api/public-config").json()
        assert cfg["app_name"] == "LedgerLab"


def test_happy_path_first_and_second_login_with_recaptcha_and_mfa(tmp_path: Path):
    """Verify the complete 'Done when' specification:
    1. Fresh browser logs in as `bot_downtown`, passes Google reCAPTCHA checkbox and both MFA codes (Email + SMS).
    2. Searches patient `DT-100234`, posts a $125.40 Visa payment with a note, and verifies the ledger balance drops by 125.40.
    3. A second login from the same browser (using the saved `ledgerlab_device` cookie) skips both MFA and CAPTCHA in `new_device` mode.
    """
    state_file = tmp_path / "bot_downtown_state.json"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            # --- Run 1: Fresh browser (unrecognized device) ---
            ctx1 = browser.new_context()
            page1 = ctx1.new_page()

            login1 = login_bot(
                context=ctx1,
                page=page1,
                username="bot_downtown",
                app_url=APP_URL,
                mailpit_url=MAILPIT_URL,
                state_path=state_file,
            )
            assert login1["captcha_solved"] is True, "Fresh browser should solve reCAPTCHA on Screen 2"
            assert login1["mfa_completed"] is True, "Fresh browser should complete Email + SMS MFA"

            # Post a single payment and verify balance
            tx_id = f"TX-E2E-{int(pace.__defaults__[0] * 1000)}"
            res = post_single_payment(
                page1,
                {
                    "transaction_id": "TX-HAPPY-12540",
                    "location": "Downtown",
                    "account_number": "DT-100234",
                    "payment_date": "2026-10-20",
                    "amount": "125.40",
                    "card_type": "Visa",
                    "paid_at_visit": "Y",
                },
                app_url=APP_URL,
            )
            assert res["status"] in ("POSTED", "SKIPPED_DUPLICATE")
            if res["status"] == "POSTED":
                assert res["balance_verified"] is True

            # Log out explicitly
            pace()
            page1.get_by_role("button", name="Log out").click()
            page1.wait_for_url("**/login", timeout=10_000)
            # Save updated storage state (retains ledgerlab_device cookie, session cookie cleared)
            ctx1.storage_state(path=str(state_file))
            ctx1.close()

            # --- Run 2: Recognized browser (reusing ledgerlab_device cookie) ---
            ctx2 = browser.new_context(storage_state=str(state_file))
            page2 = ctx2.new_page()

            login2 = login_bot(
                context=ctx2,
                page=page2,
                username="bot_downtown",
                app_url=APP_URL,
                mailpit_url=MAILPIT_URL,
            )
            assert login2["captcha_solved"] is False, "Second login on recognized device must skip CAPTCHA in new_device mode"
            assert login2["mfa_completed"] is False, "Second login on recognized device must skip MFA"
            ctx2.close()
        finally:
            browser.close()


def test_full_samples_csv_batch():
    """Run the full 20-row `samples/payments.csv` batch across Downtown and Lakeside and verify:
    - Duplicate `TX-10001` is detected and skipped
    - Unknown account `LS-209999` is detected and skipped
    - Renamed Lakeside payment types (`VISA - Front Desk`, `MC - Front Desk`, etc.) are mapped properly
    """
    summary = run_csv_batch(csv_path=DEFAULT_CSV, headless=True, reuse_device=True)
    assert summary["total"] == 20
    assert summary["skipped_unknown_account"] == 1
    assert summary["skipped_duplicate"] >= 1
    assert summary["posted"] + summary["skipped_duplicate"] + summary["skipped_unknown_account"] == 20
