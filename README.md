# LedgerLab

A mock dental practice-management app that is **only a test target for RPA bots** (Selenium vs. Playwright, POC demos).
It copies the *workflows and behavior* a payment-posting bot has to deal with: two-step login, CAPTCHA, MFA, lockouts,
session timeouts, bot detection, patient lookup, the patient ledger and payment entry. It runs on your own machine with
synthetic data. It is not affiliated with any commercial product and uses neutral branding.

Out of scope: the bots themselves, real payments, insurance, claims, scheduling, charting, real patient data.

## Quick start

```bash
cp .env.example .env      # optional, every value has a default
docker compose up --build
```

| What | URL |
|---|---|
| The app | http://localhost:8080 |
| MFA emails (Mailpit) | http://localhost:8025 |
| Dev SMS Inbox (second MFA code) | http://localhost:8080/dev/sms |
| API (direct), health check | http://localhost:8000/api/health |

Ports are configurable in `.env` (`FRONTEND_PORT`, `BACKEND_PORT`, `MAILPIT_UI_PORT`, `MAILPIT_SMTP_PORT`).

## Seeded logins

Organization: **`sunrise`** (or `Sunrise Dental Group`). Password for every user: **`LedgerLab!2026`** (`SEED_PASSWORD` in `.env`).

| Username | Role | Location(s) | Notes |
|---|---|---|---|
| `admin` | admin | Downtown, Lakeside | Only user who can open Dev Settings and the Audit Log |
| `frontdesk_downtown` | front desk | Downtown | |
| `frontdesk_lakeside` | front desk | Lakeside | |
| `bot_downtown` | automation | Downtown | Can only search patients, view ledgers and enter payments |
| `bot_lakeside` | automation | Lakeside | Same, for Lakeside |

Each user's email is `<username>@sunrise.test` and appears in Mailpit.

Patients: 20 per location (`DT-100220` … `DT-100239`, `LS-200101` … `LS-200120`), a few families, charges, adjustments
and past payments. Lakeside renames its payment types (`VISA - Front Desk`, `MC - Front Desk`, `Cash Drawer` …) while
Downtown uses `Visa`, `Mastercard`, … so a bot has to map card types per location.

## Walkthrough: the "happy path" for `bot_downtown`

1. Open http://localhost:8080, enter organization `sunrise`, username `bot_downtown`, **Continue**.
2. Enter the password, **Log In** (CAPTCHA appears first if enabled, see below).
3. New browser, so MFA: read the 6-digit code in Mailpit, enter it. Then read the second code at
   `/dev/sms` (or `GET /api/dev/sms/latest?user=bot_downtown`) and enter it.
4. Search `DT-100234`, open the ledger, **Enter Payment**: Visa, `125.40`, a note, **Save**.
5. The row appears at the top of the ledger and the balance drops by exactly 125.40.
6. Log out and log in again from the same browser: no MFA (and in `new_device` mode no CAPTCHA).

## How each feature behaves

**Login.** Screen 1: organization + username. Screen 2: password (+ CAPTCHA when required). Failed logins return a generic
message and never reveal whether the organization or user exists.

**CAPTCHA** (`CAPTCHA_PROVIDER` in `.env`: `off` or `enterprise`). `off` shows no widget and checks nothing. With
`enterprise` the page loads `https://www.google.com/recaptcha/enterprise.js`, shows the checkbox, and the backend calls
`projects.assessments.create` and accepts the login only if `tokenProperties.valid` is true. The token is checked
**before** the password. Mode (changeable on Dev Settings):

| Mode | CAPTCHA shown when |
|---|---|
| `never` | never |
| `new_device` (default) | the browser has no recognized `device_id` cookie for that user |
| `after_flag` | the account was flagged by bot detection |
| `always` | every login |

A flagged account always gets a CAPTCHA at its next login, in every mode except provider `off`.

**MFA.** Step 1: 6-digit email code (Mailpit), valid 10 minutes. Step 2 (`MFA_SMS_STEP`, default on): a 6-digit "SMS" code
written to `/dev/sms` and readable at `GET /api/dev/sms/latest?user=<username>` (no login needed, on purpose, so a bot
can read it). Five wrong codes end the login. After MFA a `device_id` cookie (90 days) is set and the device is
remembered server-side. **A login skips MFA if the device is recognized *or* the client IP is on the organization's
trusted list** (the spec's trigger wording and its "recognized devices / trusted IPs skip MFA" lines point at this
reading). A flagged account is forced through MFA again when `BOT_FLAG_FORCES_MFA` is on.
The client IP is the one nginx sees. Under Docker Desktop that is usually a gateway address such as `172.x.x.x`, not
`127.0.0.1`. The default trusted list is `203.0.113.0/24`, an unused documentation range, so every new browser goes
through MFA. Add your own address on Dev Settings to test the trusted-IP path.

**Lockouts.** 5 wrong passwords: locked 5 minutes. After the lock expires, 5 more wrong passwords: blocked until an admin
clicks *Reactivate* on Dev Settings. A successful login resets the counters. Attempts made while locked are refused and
not counted. Both events are in the audit log (`lockout`, `account_blocked`).

**Idle timeout** (`IDLE_TIMEOUT_MINUTES`, default 15). Every authenticated API call refreshes the clock. After that, the
next action redirects to login with "You were logged out due to inactivity".

**Bot detection** (`BOT_DETECTION`, default on). A session is flagged when it makes more than
`BOT_MAX_REQUESTS_PER_MIN` API requests in 60 seconds (default 60), **or** submits more than 5 forms in a row each less
than `BOT_MIN_ACTION_MS` (default 400 ms) after the previous one, meaning the 6th fast submission in a chain. Form
submissions are: patient search, ledger note search, MFA code entry, location choice and payment save. When flagged the
session ends immediately (403 `bot_detected`, then 401 with "Your session was ended because of inappropriate usage"),
the account is marked, and the next login needs a CAPTCHA (and MFA). A completed login clears the flag. Counters are in
memory, so the backend runs a single worker.

**Payments.** Amount is a string with 1 or 2 decimals, stored as integer cents. `125.40` stays `125.40`. Zero, negative,
non-numeric or 3-decimal values are rejected, never rounded. Note up to 255 characters. Payments dated before the
location's *lock transactions before* date are rejected with a clear message. **Duplicates are not prevented**; that is the
bot's job. A payment shows as a negative amount in the ledger and lowers the balance.

**Audit log.** Every login attempt, CAPTCHA event, MFA event, lockout, bot flag, logout, timeout, patient search, ledger
view and payment, with user, location, IP, time and result, plus admin actions. Admin page: `/dev/audit` with filters.

## Dev Settings (admin only, `/dev/settings`, no restart needed)

| Control | Effect |
|---|---|
| CAPTCHA mode | see table above |
| Second MFA code by SMS | on/off |
| Idle timeout | minutes |
| Bot detection on/off, max requests per minute, min ms between submissions, flag forces MFA | thresholds above |
| Trusted IPs | IPs / CIDR ranges per organization that skip MFA |
| Lock transactions before | per location; earlier payment dates are rejected |
| Payment type names | rename per location |
| **Slow mode** | random 0.5 to 4 s delay on API responses and on page transitions, with spinners. Dev tools and `/api/health` stay fast |
| **Outage mode** | HTTP 503 and a maintenance page for everything except Dev Settings (`/dev/*`), health and config. Page loads get a real 503 through nginx. Admins can still log in at `/login?dev=1` to switch it off |
| **UI changed mode** | renames visible labels ("Enter Payment" becomes "Add Payment", "Note" becomes "Memo", "Save" becomes "Post payment" and more), changes element ids and class names, and moves Save to the top of the modal |
| Reactivate / Clear devices | per user |
| Reset database | drops everything, re-seeds, restores `.env` defaults and logs everyone out |

To reset from outside the UI: `docker compose down -v && docker compose up --build` (removes the data volume).

## Create the reCAPTCHA Enterprise key

1. In the [Google Cloud console](https://console.cloud.google.com/), pick or create a project and note its **project ID**.
2. Enable the **reCAPTCHA Enterprise API** (APIs & Services, Library).
3. Security, reCAPTCHA Enterprise, **Create key**: platform **Website**, choose the **Checkbox** challenge, add the domain
   `localhost` (add any other hostname you use). Copy the **site key**.
4. APIs & Services, Credentials, **Create credentials, API key**. Restrict it to the reCAPTCHA Enterprise API. Copy it.
5. Put the three values in `.env` and switch the provider on:

```
CAPTCHA_PROVIDER=enterprise
RECAPTCHA_PROJECT_ID=your-project-id
RECAPTCHA_SITE_KEY=6Lc...
RECAPTCHA_API_KEY=AIza...
```

6. `docker compose up -d --build backend`. Open the login page in a fresh browser (no `device_id` cookie): the checkbox shows on
   the password screen.

Do not commit `.env`. Without valid values every CAPTCHA check fails closed.

## Bot-facing details

- No `data-testid` attributes and no test-only ids anywhere. Use labels, roles and visible text.
- The ledger amount column shows `-$125.40` for payments; the API returns `"-125.40"`.
- `GET /api/dev/sms/latest?user=bot_downtown` returns `{ "code": "123456", ... }` for the second MFA code.
- Mailpit REST API (`http://localhost:8025/api/v1/messages`) gives bots the email code.
- `samples/payments.csv`: 20 test payments (transaction ID, location, account number, date, amount string, card type,
  paid-at-visit flag), with one duplicate transaction ID (`TX-10001` twice) and one unknown account (`LS-209999`).

## Run without Docker (development)

```bash
# backend (Python 3.12)
cd backend
python -m venv .venv && .venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
set SMTP_HOST=                                         # empty: emails are logged to the console instead of sent
uvicorn app.main:app --port 8000

# frontend (Node 20+), proxies /api to :8000
cd frontend
npm install
npm run dev                                            # http://localhost:5173
```

With `SMTP_HOST` empty the MFA email text is printed in the backend log (`MAIL (no SMTP_HOST ...)`). Or run Mailpit
separately and set `SMTP_HOST=localhost`.

## Tests

```bash
cd backend
pip install -r requirements.txt
python -m pytest -q
```

Covers login and lockout rules, MFA rules, CAPTCHA modes (Google call mocked), bot detection, idle timeout, amount
handling, locked dates, location scoping, chaos switches and the audit log.

## Layout

```
backend/    FastAPI + SQLAlchemy + SQLite (app/, tests/)
frontend/   React + Vite + TypeScript SPA, nginx config
samples/    payments.csv
docker-compose.yml, .env.example
```
