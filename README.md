# LedgerLab

A mock dental practice-management app that is **only a test target for RPA bots** (Selenium vs. Playwright, POC demos).
It copies the *workflows and behavior* a payment-posting bot has to deal with: two-step login, CAPTCHA, MFA, lockouts,
session timeouts, bot detection, patient lookup, the patient ledger and payment entry. It runs on your own machine with
synthetic data. It is not affiliated with any commercial product and uses neutral branding.

Out of scope: real payments, insurance, claims, scheduling, charting, real patient data.

Included in this repo:
- **`backend/`** & **`frontend/`**: The LedgerLab web application (FastAPI + React SPA + Mailpit).
- **`rpa/`**: A working **Playwright RPA payment-posting bot** and end-to-end test suite (`rpa/post_payments.py`, `rpa/test_rpa_e2e.py`).
- **`samples/payments.csv`**: 20 synthetic card payments (including a duplicate transaction ID and an unknown account number) for testing the bot.

## Run it locally (step by step)

Everything runs in Docker with one command. You do not need Python or Node installed.

### 1. Prerequisites

| You need | Notes |
|---|---|
| **Docker Desktop** (or Docker Engine + the Compose plugin) | https://www.docker.com/products/docker-desktop/ |
| **Git** | to clone the repo |
| Free ports **8080, 8000, 8025, 1025** | changeable in `.env`, see below |

**Windows only:** Docker Desktop needs WSL 2. If Docker says the engine can't start, open **PowerShell as
Administrator**, run `wsl --install --no-distribution`, reboot, then start Docker Desktop and wait until it shows
"Engine running". (Windows 11 Home has no other option; virtualization must be enabled in the BIOS.)

### 2. Get the code

```bash
git clone -b ledgerlab-mock-app https://github.com/nimjj/RPA-test-dentrix-duplicate.git
cd RPA-test-dentrix-duplicate
```

### 3. Configure (optional)

```bash
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
```

Every value has a default, so you can skip this step. Edit `.env` to change ports, the seed password, CAPTCHA settings
and so on. Never commit `.env`.

### 4. Start everything

```bash
docker compose up --build
```

The first run downloads images and builds the app, which takes a few minutes. It is ready when the log shows the
backend as healthy and nginx started. Add `-d` to run in the background (`docker compose up --build -d`).

### 5. Check that it works

| What | URL | You should see |
|---|---|---|
| Health check | http://localhost:8000/api/health | `{"status":"ok"}` |
| **The app** | http://localhost:8080 | the LedgerLab login page |
| MFA emails (Mailpit) | http://localhost:8025 | an empty inbox, filling up as you log in |
| Dev SMS Inbox (second MFA code) | http://localhost:8080/dev/sms | an empty message list |

### 6. Log in for the first time

Organization `sunrise`, username `bot_downtown`, password `LedgerLab!2026`. Because the browser is new you will see the
**Google reCAPTCHA checkbox** on the password screen (`CAPTCHA_PROVIDER=test` is enabled by default using Google's
official localhost test keys), followed by two MFA codes: the **email code** (open Mailpit at http://localhost:8025,
open the newest message) and the **SMS code** (the `/dev/sms` page at http://localhost:8080/dev/sms). Then search
`DT-100234`. The full click-by-click walkthrough is further down.
All seeded users are listed under [Seeded logins](#seeded-logins).

### 7. Stop, restart, reset

```bash
docker compose stop              # stop, keep your data
docker compose up -d             # start again
docker compose down              # remove containers, keep data (named volume)
docker compose down -v           # remove containers AND data: a fresh seeded database next time
```

You can also reset the data from the app: log in as `admin`, open **Dev Settings**, **Reset database to seed data**.
After changing code or `.env`, run `docker compose up --build -d` again.

### Troubleshooting

| Problem | Fix |
|---|---|
| `failed to connect to the docker API` / `dockerDesktopLinuxEngine` not found | Docker Desktop isn't running. Start it and wait for "Engine running". On Windows also see the WSL 2 note above |
| `port is already allocated` / `address already in use` | Another program uses 8080, 8000, 8025 or 1025. Set `FRONTEND_PORT`, `BACKEND_PORT`, `MAILPIT_UI_PORT` or `MAILPIT_SMTP_PORT` in `.env`, then `docker compose up -d` |
| Login always asks for MFA | Expected for a new browser. A login skips MFA only for a recognized device (cookie) or a trusted IP. Under Docker Desktop the app sees your IP as a gateway address such as `172.18.0.1` (check the **IP** column in the Audit Log). Add it under Dev Settings, Trusted IPs, to skip MFA |
| No email code in Mailpit | Open http://localhost:8025 (not the app port). Check `docker compose logs mailpit backend` |
| I locked myself out | 5 wrong passwords lock the account for 5 minutes; 5 more block it until an admin clicks **Reactivate** in Dev Settings. Or reset the data (step 7) |
| Everything shows "Down for maintenance" | Outage mode is on. Open http://localhost:8080/login?dev=1, log in as `admin`, open Dev Settings and untick it |
| "You were logged out due to inactivity" / "inappropriate usage" | The idle timeout (default 15 min) or bot detection ended your session. Both are working as designed, and both are adjustable in Dev Settings |
| Something else is wrong | `docker compose ps` and `docker compose logs backend frontend` show what each service is doing |

CAPTCHA is enabled out of the box in **test mode** (`CAPTCHA_PROVIDER=test`), which renders the real Google reCAPTCHA
checkbox using Google's official localhost test keys (no Google Cloud account required). To switch to your own Google
Cloud reCAPTCHA Enterprise project or turn it off, see [CAPTCHA configuration](#create-the-recaptcha-enterprise-key).

### Ports and URLs at a glance

| What | URL |
|---|---|
| The app | http://localhost:8080 |
| MFA emails (Mailpit) | http://localhost:8025 |
| Dev SMS Inbox | http://localhost:8080/dev/sms |
| API (direct) | http://localhost:8000/api/health |

Ports are configurable in `.env` (`FRONTEND_PORT`, `BACKEND_PORT`, `MAILPIT_UI_PORT`, `MAILPIT_SMTP_PORT`).
The compose file publishes these ports on all network interfaces. On a shared network, bind them to `127.0.0.1`.

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

**CAPTCHA** (`CAPTCHA_PROVIDER` in `.env`: `test`, `enterprise`, or `off`).
- `test` (default): loads `https://www.google.com/recaptcha/enterprise.js` with Google's official localhost test site key (`6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI`), renders the real "I'm not a robot" checkbox widget, and verifies the token via Google's `siteverify` endpoint. Works immediately with zero cloud setup.
- `enterprise`: uses your own Google Cloud reCAPTCHA Enterprise keys (`RECAPTCHA_PROJECT_ID`, `RECAPTCHA_SITE_KEY`, `RECAPTCHA_API_KEY`) and calls `projects.assessments.create`, accepting the login only if `tokenProperties.valid` is true.
- `off`: shows no widget and checks nothing.

The token is checked **before** the password. Mode (changeable on Dev Settings):

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

## Run the Playwright RPA Bot & Tests

The `rpa/` directory contains a complete Playwright RPA bot (`rpa/post_payments.py`) and end-to-end test suite (`rpa/test_rpa_e2e.py`) that:
1. Logs into LedgerLab (`sunrise` / `bot_downtown` and `bot_lakeside`).
2. Detects and clicks the **Google reCAPTCHA checkbox** on Login Screen 2 (and pauses for human interaction in `--headed` mode if an image challenge appears).
3. Automatically retrieves the **6-digit Email MFA code** from the Mailpit REST API (`http://localhost:8025/api/v1/messages`) and the **6-digit SMS MFA code** from `GET /api/dev/sms/latest`.
4. Saves the 90-day `ledgerlab_device` cookie (`rpa/.auth/<user>.json`) so subsequent runs skip CAPTCHA and MFA in `new_device` mode.
5. Reads `samples/payments.csv`, searches each patient by account number, filters ledger notes by `transaction_id` to **skip duplicates** (`TX-10001`), skips unknown accounts (`LS-209999`), maps location-specific card labels (`Visa` vs. `VISA - Front Desk`), and paces requests to stay under LedgerLab's bot-detection limits (`BOT_MIN_ACTION_MS = 400ms` and `BOT_MAX_REQUESTS_PER_MIN = 60`).

### 1. Install Playwright (one-time setup)

Make sure the Docker stack is running (`docker compose up --build -d`) and Python 3.10+ is installed on your machine:

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt -r rpa/requirements.txt
playwright install chromium
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt -r rpa/requirements.txt
playwright install chromium
```

### 2. Watch the Playwright RPA Bot in a Visible Browser (`--headed`)

Run a quick 3-payment demo in a visible Chromium window with a fresh device (forces reCAPTCHA + Email MFA + SMS MFA):

```bash
python rpa/post_payments.py --headed --fresh-device --limit 3
```

Run the full 20-row `samples/payments.csv` batch across both Downtown and Lakeside locations:

```bash
python rpa/post_payments.py --headed
```

After each run, a detailed JSON report is written to `rpa/last_run_report.json`.

### 3. Run Automated Tests (Playwright E2E + Backend Unit Tests)

**Run the live Playwright E2E test suite** (requires `docker compose up -d` running on `:8080`, `:8000`, `:8025`):

```bash
pytest rpa/test_rpa_e2e.py -v -s
```

What `rpa/test_rpa_e2e.py` tests:
- `test_happy_path_first_and_second_login_with_recaptcha_and_mfa`: Fresh browser solves reCAPTCHA, completes Email + SMS MFA, posts a `$125.40` Visa payment to `DT-100234`, verifies the updated balance, logs out, and logs back in with the saved device cookie to verify that **both CAPTCHA and MFA are skipped on the second login**.
- `test_full_samples_csv_batch`: Runs all 20 rows of `samples/payments.csv` and verifies that duplicate `TX-10001` and unknown account `LS-209999` are properly skipped.

**Run the backend unit test suite** (116 tests, runs in-memory without Docker):

```bash
pytest backend/tests -q
```

## Layout

```
backend/    FastAPI + SQLAlchemy + SQLite (app/, tests/)
frontend/   React + Vite + TypeScript SPA, nginx config
rpa/        Playwright RPA payment-posting bot & E2E tests (helpers.py, post_payments.py, test_rpa_e2e.py)
samples/    payments.csv
docker-compose.yml, .env.example
```
