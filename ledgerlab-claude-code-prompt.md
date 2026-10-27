# Build LedgerLab: a mock dental practice-management app for RPA testing

## Context

We're an engineering team preparing to build an RPA bot that posts card payments into a cloud dental practice-management system (Dentrix Ascend). We can't test against the real product yet, so we need our own stand-in that behaves like it in the areas that matter to a bot: login security (CAPTCHA, MFA, lockouts, session timeouts, bot detection), patient lookup, the patient ledger, and payment entry.

LedgerLab is an internal test target only. It runs on our own machines with synthetic data. We'll use it to compare a Selenium bot and a Playwright bot, and to demo a working POC.

Mirror the **workflows and behavior**, not the branding. Do not use the Dentrix or Henry Schein One name, logo, colors or visual design anywhere. Use a plain, neutral UI.

**Out of scope:** the bots themselves, real payments, insurance, claims, scheduling, charting, real patient data.

## Tech stack

- Frontend: React + Vite + TypeScript, React Router (single-page app), plain CSS or Tailwind.
- Backend: Python FastAPI, SQLite via SQLAlchemy, session cookies (HTTP-only), server-side session store in SQLite.
- Email: Mailpit (Docker image `axllent/mailpit`, SMTP 1025, web UI 8025) to capture MFA emails.
- Everything starts with one `docker compose up`: frontend, backend, Mailpit.
- Config through a `.env` file, with a committed `.env.example`.

## Features to build

### 1. Login flow (two-step, like the real product)

1. Screen 1: **Organization** and **Username**, then **Continue**.
2. Screen 2: **Password**, then **Log In**.
3. If required (see CAPTCHA modes below), show a reCAPTCHA checkbox on screen 2. The backend must verify the token before checking the password.
4. If MFA is required (see below), go to an MFA screen before the user lands in the app.
5. After login, the user picks a **Location** if their organization has more than one, then lands on the patient search page.

### 2. CAPTCHA

- Use Google reCAPTCHA (Google Cloud "Checkbox" key). Frontend loads `https://www.google.com/recaptcha/enterprise.js` and renders the checkbox widget. Backend verifies by calling the reCAPTCHA Enterprise `projects.assessments.create` endpoint with `RECAPTCHA_PROJECT_ID`, `RECAPTCHA_SITE_KEY` and `RECAPTCHA_API_KEY` from `.env`, and accepts the login only if `tokenProperties.valid` is true.
- `CAPTCHA_PROVIDER` setting: `off` (no widget, for early development), `enterprise` (real Google check).
- `CAPTCHA_MODE` setting, changeable at runtime from the Dev Settings page:
  - `never`
  - `new_device`: only when the browser has no recognized device cookie (default)
  - `after_flag`: only after the account was flagged by bot detection (see 5)
  - `always`
- Log every CAPTCHA shown, passed and failed in the audit log.

### 3. MFA

- Trigger MFA when the login comes from an unrecognized device (no valid `device_id` cookie) **or** an IP not on the organization's trusted IP list.
- Step 1: a 6-digit code sent by email (through Mailpit) to the user's registered address, valid 10 minutes.
- Step 2 (setting `MFA_SMS_STEP`, default on): a second 6-digit code "sent by SMS". There's no real SMS: write it to a **Dev SMS Inbox** page (`/dev/sms`) and expose it at `GET /api/dev/sms/latest?user=...` so a bot can read it.
- After successful MFA, set a long-lived `device_id` cookie (90 days) and remember the device server-side. Recognized devices skip MFA.
- Admin can clear a user's registered devices.
- Trusted IPs per organization, editable on the Dev Settings page. Logins from a trusted IP skip MFA (but still follow `CAPTCHA_MODE`).

### 4. Lockouts

- 5 wrong passwords: account locked for 5 minutes.
- 5 more wrong passwords after that: account blocked until an admin reactivates it on the Dev Settings page.
- Both events go in the audit log.

### 5. Session timeout and bot detection

- Inactivity timeout (setting `IDLE_TIMEOUT_MINUTES`, default 15). After that, any action redirects to login with the message "You were logged out due to inactivity".
- Simple bot-detection heuristic (setting `BOT_DETECTION`, default on). Flag the session as "inappropriate usage" if **either**:
  - more than `BOT_MAX_REQUESTS_PER_MIN` API requests in a minute (default 60), or
  - more than 5 consecutive form submissions less than `BOT_MIN_ACTION_MS` apart (default 400 ms).
- When flagged: end the session immediately and mark the account so the next login requires CAPTCHA (and MFA if `BOT_FLAG_FORCES_MFA` is on, default on).

### 6. Locations and users

- An organization has several locations. Each user is assigned to one or more locations.
- Seed: one organization "Sunrise Dental Group" with two locations (Downtown, Lakeside).
- Seed users: one admin, one front-desk user per location, and one **automation user per location** (`bot_downtown`, `bot_lakeside`) that can only search patients, view the ledger and enter payments.

### 7. Patients

- Each patient has: account number (e.g. `DT-100234`), first and last name, date of birth, location, guarantor (self or another patient in the same family), current balance.
- Patient search by **account number** or name, scoped to the user's current location. A patient from another location must not appear.
- Seed 20 patients per location, a few in families, with realistic synthetic balances.

### 8. Patient ledger

- Ledger page per patient: a table with date, transaction type (charge, payment, adjustment), payment type, description/note, amount and running balance, newest first.
- Search box on the ledger that filters by text in the note (so a bot can look for a transaction ID).
- Seed a few charges and past payments per patient.

### 9. Payment entry

- An **Enter Payment** button on the ledger opens a modal with:
  - Payment type: dropdown from the location's configured payment types (seed: Visa, Mastercard, Amex, Discover, Cash, Check). Each location can rename them, e.g. "VISA - Front Desk", so a bot has to map card types per location.
  - Amount: text field, stored as a decimal with exactly 2 places. Reject 0 or negative values. Never round.
  - Payment date: date picker.
  - Apply to: "Today's visit" or "Account balance" (mirrors paid-at-visit).
  - Note: free text, up to 255 characters.
- **Save** shows a success toast and the new row appears in the ledger. The balance updates.
- Locked dates: a "lock transactions before" date per location (Dev Settings). Payments dated before it are rejected with a clear error message.
- The app does **not** prevent duplicates on its own (the real system doesn't either). Duplicate protection is the bot's job.

### 10. Audit log

Record every login attempt, CAPTCHA event, MFA event, lockout, bot flag, logout, timeout, patient search, ledger view and payment, with user, location, IP, time and result. Show it on an admin page with filters.

### 11. Dev Settings page (admin only)

One page to change, at runtime with no restart:

- `CAPTCHA_MODE`, `MFA_SMS_STEP`, trusted IPs, `IDLE_TIMEOUT_MINUTES`, bot-detection on/off and its thresholds.
- **Chaos switches** to test bot resilience:
  - **Slow mode**: random 0.5 to 4 second delays on API responses and page transitions, with loading spinners.
  - **Outage mode**: return HTTP 503 with a maintenance page for all requests except Dev Settings.
  - **UI changed mode**: rename visible labels (e.g. "Enter Payment" becomes "Add Payment", "Note" becomes "Memo"), change element ids and class names, and move the Save button to a different position in the modal.
- Buttons: reactivate blocked users, clear devices for a user, reset the database to seed data.

## UI realism rules

- It's an SPA with client-side routing, modals and toasts, like a modern cloud app.
- **No `data-testid` attributes** and no ids added just for testing. Bots should have to rely on visible labels, roles and normal markup, as they would on the real product.
- Show loading spinners while data loads, so bots have to wait properly.
- Keep the design plain and functional.

## Developer extras

- `README.md`: setup, `.env` values, how to create the reCAPTCHA key, seeded logins, how to reset data, how to use each Dev Settings switch.
- A `payments.csv` sample in `/samples` with 20 test payments (transaction ID, location, account number, date, amount as a string with 2 decimals, card type, paid-at-visit flag), including one duplicate transaction ID and one unknown account number.
- Health check at `GET /api/health`.

## How to work

1. Start by writing a short plan (data model, API routes, pages) and wait for my OK.
2. Build in stages, and after each stage tell me how to run and check it:
   1. Docker Compose, backend skeleton, database and seed data.
   2. Login flow, lockouts and sessions, with `CAPTCHA_PROVIDER=off`.
   3. MFA (email via Mailpit and the Dev SMS Inbox), device cookie, trusted IPs.
   4. Patients, ledger and payment entry.
   5. reCAPTCHA (`enterprise`), CAPTCHA modes, bot detection, idle timeout.
   6. Dev Settings, chaos switches and audit log.
   7. README and samples.
3. Write backend tests (pytest) for: login and lockout rules, MFA rules, CAPTCHA modes, bot detection, amount handling (125.40 stays 125.40), locked dates and location scoping.

## Done when

- `docker compose up` starts everything on a clean machine.
- A person can log in as `bot_downtown`, pass the CAPTCHA and both MFA codes, search a patient by account number, post a $125.40 Visa payment with a note, and see it on the ledger with the right balance.
- A second login from the same browser skips MFA, and in `new_device` mode skips the CAPTCHA too.
- Idle timeout, lockouts, bot detection and all three chaos switches work as described and show up in the audit log.
- No Dentrix or Henry Schein One branding appears anywhere.
