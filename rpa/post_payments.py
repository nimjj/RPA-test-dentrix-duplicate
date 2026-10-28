"""Playwright RPA Payment-Posting Bot for LedgerLab.

Reads `samples/payments.csv` (or a custom CSV path), logs in per location using
`bot_downtown` / `bot_lakeside`, checks each patient's ledger for duplicate
transaction IDs before posting, maps location-specific card labels, and saves a
structured run report.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import (
    SessionRateGuard,
    login_bot,
    pace,
    select_Matching_payment_type,
)

LOCATION_BOT_USERS = {
    "downtown": "bot_downtown",
    "lakeside": "bot_lakeside",
}

AUTH_DIR = Path(__file__).resolve().parent / ".auth"
DEFAULT_CSV = Path(__file__).resolve().parent.parent / "samples" / "payments.csv"
DEFAULT_REPORT = Path(__file__).resolve().parent / "last_run_report.json"


def parse_money_to_cents(text: str) -> int:
    """Convert formatted currency like '$1,250.40' or '-$125.40' to integer cents."""
    cleaned = text.strip().replace("$", "").replace(",", "")
    sign = -1 if cleaned.startswith("-") else 1
    cleaned = cleaned.lstrip("+-")
    parts = cleaned.split(".")
    dollars = int(parts[0])
    cents = int(parts[1]) if len(parts) > 1 else 0
    return sign * (dollars * 100 + cents)


def post_single_payment(page: Page, row: dict[str, str], app_url: str = "http://localhost:8080") -> dict[str, Any]:
    """Process a single payment row in the UI and return its outcome."""
    tx_id = row["transaction_id"].strip()
    account_no = row["account_number"].strip()
    payment_date = row["payment_date"].strip()
    amount = row["amount"].strip()
    card_type = row["card_type"].strip()
    paid_at_visit = row["paid_at_visit"].strip().upper() == "Y"
    note_text = f"{tx_id} - RPA card payment ({card_type})"

    # 1. Navigate to Patient Search using SPA link if on ledger, avoiding full-page reload API calls
    if not page.url.endswith("/patients"):
        back_link = page.get_by_role("link", name=re.compile(r"Patients", re.I))
        if back_link.count() > 0 and back_link.first.is_visible():
            back_link.first.click()
            page.wait_for_url("**/patients", timeout=10_000)
        else:
            page.goto(f"{app_url}/patients")

    search_input = page.get_by_label(re.compile(r"^(Search patients|Find a patient)$", re.I))
    search_input.wait_for(state="visible", timeout=10_000)
    search_input.fill(account_no)
    pace()
    page.get_by_role("button", name=re.compile(r"^(Search|Find)$", re.I)).click()

    # Wait for results or "No patients found"
    no_found = page.get_by_text(re.compile(r"No patients found", re.I))
    account_link = page.get_by_role("link", name=account_no)
    page.wait_for_timeout(250)
    if no_found.is_visible():
        return {
            "transaction_id": tx_id,
            "account_number": account_no,
            "amount": amount,
            "status": "SKIPPED_UNKNOWN_ACCOUNT",
            "detail": f"Account {account_no} not found in location {row['location']}",
        }

    expect(account_link).to_be_visible(timeout=10_000)
    account_link.click()

    # 2. On Patient Ledger page: check for duplicate transaction_id in notes first
    filter_input = page.get_by_label(re.compile(r"^(Search notes|Filter memos)$", re.I))
    filter_input.wait_for(state="visible", timeout=10_000)
    balance_el = page.locator("dd.balance")
    balance_before_cents = parse_money_to_cents(balance_el.inner_text())

    filter_input.fill(tx_id)
    pace()
    page.get_by_role("button", name=re.compile(r"^(Search|Apply)$", re.I)).click()

    # Wait for spinner to clear
    page.locator(".spinner-wrap").wait_for(state="detached", timeout=10_000)
    existing_cell = page.locator("table tbody tr td", has_text=tx_id)
    if existing_cell.count() > 0:
        return {
            "transaction_id": tx_id,
            "account_number": account_no,
            "amount": amount,
            "status": "SKIPPED_DUPLICATE",
            "detail": f"Transaction {tx_id} already exists on ledger for {account_no}",
        }

    # 3. Open Enter Payment Modal
    page.get_by_role("button", name=re.compile(r"^(Enter Payment|Add Payment)$", re.I)).click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible(timeout=10_000)

    pay_type_select = dialog.get_by_label(re.compile(r"^(Payment type|Method of payment)$", re.I))
    pay_type_select.wait_for(state="visible", timeout=10_000)
    mapped_label = select_Matching_payment_type(pay_type_select, card_type)

    dialog.get_by_label(re.compile(r"^(Amount|Payment amount)$", re.I)).fill(amount)
    dialog.get_by_label(re.compile(r"^(Payment date|Date received)$", re.I)).fill(payment_date)

    apply_select = dialog.get_by_label(re.compile(r"^(Apply to|Allocate to)$", re.I))
    apply_select.select_option("todays_visit" if paid_at_visit else "account_balance")

    dialog.get_by_label(re.compile(r"^(Note|Memo)$", re.I)).fill(note_text)

    pace()
    dialog.get_by_role("button", name=re.compile(r"^(Save|Post payment)$", re.I)).click()

    # Wait for modal to close and toast / updated balance
    expect(dialog).to_be_hidden(timeout=10_000)
    page.locator(".spinner-wrap").wait_for(state="detached", timeout=10_000)

    balance_after_cents = parse_money_to_cents(balance_el.inner_text())
    expected_delta_cents = parse_money_to_cents(amount)

    return {
        "transaction_id": tx_id,
        "account_number": account_no,
        "location": row["location"],
        "amount": amount,
        "mapped_payment_type": mapped_label,
        "balance_before": f"{balance_before_cents / 100:.2f}",
        "balance_after": f"{balance_after_cents / 100:.2f}",
        "balance_verified": (balance_before_cents - balance_after_cents) == expected_delta_cents,
        "status": "POSTED",
    }


def run_csv_batch(
    csv_path: Path = DEFAULT_CSV,
    app_url: str = "http://localhost:8080",
    mailpit_url: str = "http://localhost:8025",
    headless: bool = True,
    limit: int | None = None,
    reuse_device: bool = True,
) -> dict[str, Any]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if limit is not None:
        rows = rows[:limit]

    # Group rows by location while preserving order per location
    by_location: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        loc_key = r["location"].strip().lower()
        by_location.setdefault(loc_key, []).append(r)

    results: list[dict[str, Any]] = []
    login_summaries: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            for loc_key, loc_rows in by_location.items():
                bot_user = LOCATION_BOT_USERS[loc_key]
                state_file = AUTH_DIR / f"{bot_user}.json"
                ctx_kwargs: dict[str, Any] = {}
                if reuse_device and state_file.exists():
                    ctx_kwargs["storage_state"] = str(state_file)

                context = browser.new_context(**ctx_kwargs)
                # Clear session_id cookie if storage_state had an old active session, keeping only device_id
                if reuse_device and state_file.exists():
                    cookies = [c for c in context.cookies() if c["name"] == "ledgerlab_device"]
                    context.clear_cookies()
                    if cookies:
                        context.add_cookies(cookies)

                page = context.new_page()
                guard = SessionRateGuard(page)
                login_info = login_bot(
                    context=context,
                    page=page,
                    username=bot_user,
                    app_url=app_url,
                    mailpit_url=mailpit_url,
                    state_path=state_file if reuse_device else None,
                )
                login_summaries.append(login_info)

                for row in loc_rows:
                    # Proactively rotate the session before hitting BOT_MAX_REQUESTS_PER_MIN (60/min)
                    if guard.needs_session_refresh():
                        pace()
                        logout_btn = page.get_by_role("button", name=re.compile(r"^(Log out|Sign out)$", re.I))
                        if logout_btn.count() > 0 and logout_btn.is_visible():
                            logout_btn.click()
                            page.wait_for_url("**/login", timeout=10_000)
                        guard.reset_counter()
                        relogin_info = login_bot(
                            context=context,
                            page=page,
                            username=bot_user,
                            app_url=app_url,
                            mailpit_url=mailpit_url,
                            state_path=state_file if reuse_device else None,
                        )
                        login_summaries.append(relogin_info)

                    res = post_single_payment(page, row, app_url=app_url)
                    results.append(res)
                    print(f"[{res['status']}] {res['transaction_id']} | {res['account_number']} | ${res['amount']}")

                context.close()
        finally:
            browser.close()

    summary = {
        "total": len(results),
        "posted": sum(1 for r in results if r["status"] == "POSTED"),
        "skipped_duplicate": sum(1 for r in results if r["status"] == "SKIPPED_DUPLICATE"),
        "skipped_unknown_account": sum(1 for r in results if r["status"] == "SKIPPED_UNKNOWN_ACCOUNT"),
        "logins": login_summaries,
        "results": results,
    }
    DEFAULT_REPORT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the LedgerLab Playwright RPA Payment Bot")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Path to payments.csv")
    parser.add_argument("--headed", action="store_true", help="Run Chromium in visible headed mode")
    parser.add_argument("--fresh-device", action="store_true", help="Do not reuse saved device_id cookie")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of CSV rows to process")
    args = parser.parse_args()

    report = run_csv_batch(
        csv_path=args.csv,
        headless=not args.headed,
        limit=args.limit,
        reuse_device=not args.fresh_device,
    )
    print(
        f"\nDone! Posted: {report['posted']}, "
        f"Duplicates skipped: {report['skipped_duplicate']}, "
        f"Unknown accounts skipped: {report['skipped_unknown_account']}"
    )
