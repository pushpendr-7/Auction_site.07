# BidBazaar Auction Website — Project Brain

> **Purpose:** This file is the primary project context for future AI-assisted work.
> Read it before changing this project. It explains what the app does, how it
> runs, where the real code lives, what has already been fixed, what is still
> risky, and what must not be changed casually.

## 1. How to use this file

1. Read this file before starting any task in this repository.
2. Treat the current source code as the final source of truth if this document
   and the code ever disagree.
3. Before editing, inspect the relevant source files and the current git status.
4. Preserve existing auction, wallet, payment, and bidding behavior unless the
   user explicitly asks for a product or business-rule change.
5. After a meaningful change, run the smallest relevant checks, then run the
   complete verification commands listed near the end of this file.
6. Update this file only when a durable architecture decision, workflow rule,
   deployment fact, or known limitation changes. Do not use it as a changelog
   for every small edit.

This document is project guidance. It does not override platform, security, or
user instructions.

## 2. Product identity

- **Product:** BidBazaar Auctions
- **Type:** Django server-rendered online auction marketplace
- **Main users:** sellers/listing owners, auction participants/bidders, winners,
  and staff/admin users
- **Current UI style:** dark Bootstrap-based interface with BidBazaar branding
- **Main time zone:** `Asia/Kolkata`
- **Main market window:** bidding is allowed from 06:00 until 01:00 local time
- **Current empty-state behavior:** a fresh local database may show no auctions.
  That is an empty database state, not automatically a rendering failure.
- **Primary app:** the Django code under `auction_site/`, `auctions/`, and
  `templates/`
- **Not the primary app:** the generic Node/PNPM scaffold under `lib/` and
  `artifacts/api-server/src/`; do not add auction business logic there.

## 3. Important safety rules

- Never put passwords, API keys, tokens, session values, database URLs,
  private keys, bank secrets, or other credentials in this file, source code,
  chat, logs, or screenshots.
- Environment variable **names** may be documented; environment variable
  **values** must stay in Replit Secrets or the deployment environment.
- The project currently uses `SESSION_SECRET` as an allowed source for Django's
  secret key. Never add a public fallback secret.
- Do not migrate SQLite data, delete data, replace the database, or change
  payment/settlement behavior without explaining the risk and getting approval.
- Do not assume a payment callback, bank UTR, blockchain transaction, or email
  verification is genuine just because a browser request was made.
- Do not expose seller addresses, bank details, booking codes, or personal data
  to users who are not authorized to see them.
- Do not make a state-changing endpoint GET-only. Prefer POST plus CSRF
  protection for logout, booking, payments, settlement, and other mutations.
- Do not weaken authentication, authorization, CSRF, XSS, or deployment security
  just to make a preview work.
- Do not add sample auctions or fake payments to a user's database without
  explicit permission.

## 4. Runtime and stack

### Actual application stack

- Python 3.11
- Django 5.2.x (currently pinned to the available compatible 5.2.17)
- Django Channels and Daphne for HTTP plus WebSockets
- SQLite by default for development
- PostgreSQL-compatible database when `DATABASE_INTERNAL_URL` or `DATABASE_URL`
  is configured
- WhiteNoise for collected static files
- Optional Cloudinary media storage
- Optional Redis channel layer
- Optional Web3/Polygon payment verification
- Bootstrap and Django templates for the web UI

### Entry points

- `manage.py` — Django command entry point
- `auction_site/settings.py` — environment-driven configuration
- `auction_site/urls.py` — project-level URL routing, admin, SEO, media
- `auction_site/asgi.py` — HTTP and WebSocket application
- `auction_site/wsgi.py` — WSGI application for traditional hosts such as
  PythonAnywhere
- `auctions/urls.py` — complete auction HTTP route table
- `auctions/views.py` — most HTTP and business logic
- `auctions/models.py` — database schema/model behavior
- `auctions/forms.py` — wallet, bid, and bank-link forms
- `auctions/utils.py` — wallet/payment/ledger helpers
- `auctions/blockchain.py` — Web3 transaction verification helpers
- `auctions/consumers.py` and `auctions/routing.py` — live auction WebSocket
- `templates/auctions/` — user-facing HTML
- `static/css/site.css` and `static/js/site.js` — frontend assets
- `requirements.txt` — authoritative Python dependencies

## 5. Directory map

```text
auction_site/
  settings.py       Environment, database, security, storage, email, channels
  urls.py            Admin, robots, sitemap, app include, favicon, media
  asgi.py            Django Channels HTTP/WebSocket entry point
  wsgi.py            WSGI entry point for PythonAnywhere-style hosting

auctions/
  models.py          Auction, bid, participant, payment, wallet, order, audit
  views.py           Main HTTP workflows and business rules
  forms.py           Bid, recharge, bank-link forms
  urls.py            Auction URL routes
  utils.py           Payment effects, wallet holds, booking codes, ledger
  blockchain.py      Polygon/Web3 validation
  consumers.py       Live bid WebSocket consumer
  routing.py         WebSocket URL patterns
  admin.py           Registered Django admin models
  migrations/        Database schema history, currently through 0016
  management/
    commands/        Settlement, backup, restore, retention commands
  tests.py           Small wallet-hold and bid transaction tests

templates/
  auctions/          Base, home, detail, auth, wallet, payment, call pages
  404.html           Custom not-found page
  500.html           Custom server-error page

static/
  css/site.css       Main site styles
  js/site.js         Small global frontend script
  favicon.*          Site icons and manifest

media/
  items/             Local uploaded auction images during development

artifacts/
  api-server/        Replit artifact wrapper routing the Django app at /
  mockup-sandbox/    Separate component-preview/canvas service

lib/
  api-client-react/
  api-spec/
  api-zod/
  db/                Generic scaffold packages, not the auction UI source
```

## 6. How the application starts

### Replit development workflow

The root workflow is configured in `.replit`:

```text
bash start_django.sh
```

`start_django.sh`:

1. Finds its own directory instead of assuming a hard-coded workspace path.
2. Uses Python 3.11 when available.
3. Sets `DJANGO_SETTINGS_MODULE` and `PYTHONPATH`.
4. Enables `DJANGO_DEBUG=true` only for a non-deployment Replit preview.
5. Runs `manage.py migrate --noinput`.
6. Runs `manage.py collectstatic --noinput`.
7. Optionally creates a superuser only when
   `DJANGO_SUPERUSER_PASSWORD` is configured.
8. Starts Daphne on `$PORT`, defaulting to port 8000.

### Managed artifact preview

`artifacts/api-server/.replit-artifact/artifact.toml` is the Replit routing
wrapper for the real Django app. It is intentionally configured as:

- title: `Auction Website`
- preview path: `/`
- local port: `8000`
- development command: `bash ../../start_django.sh`
- production command: `bash ../../start_django.sh`

The artifact directory is not the place for auction business logic. If the
preview stops showing the Django site, first check the artifact's route, local
port, working directory, and workflow before changing application code.

### Production deployment configuration

`.replit` uses:

- deployment target: autoscale
- build: `pip install -r requirements.txt`
- run: `bash start_django.sh`

The managed artifact also has its own production build/run configuration. Check
both `.replit` and `artifacts/api-server/.replit-artifact/artifact.toml` when
debugging publishing.

## 7. Configuration and environment variables

Never write values in this file. These are the important variable names:

### Required or core

- `SECRET_KEY` or `SESSION_SECRET`
- `DJANGO_DEBUG`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `PORT`
- `DATABASE_INTERNAL_URL` or `DATABASE_URL`
- `MEDIA_ROOT`

### Production persistence and realtime

- `REDIS_URL` — required for a shared multi-instance Channels layer
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

### Email and verification

- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `DEFAULT_FROM_EMAIL`

Without SMTP credentials, Django intentionally falls back to the console email
backend. Email verification/OTP cannot be considered production-ready until
SMTP delivery is configured and tested.

### Payments and blockchain

- `PLATFORM_UPI_VPA`
- `PLATFORM_BANK_HOLDER_NAME`
- `PLATFORM_BANK_ACCOUNT_NUMBER`
- `PLATFORM_BANK_IFSC`
- `BLOCKCHAIN_ENABLED`
- `BLOCKCHAIN_NETWORK_NAME`
- `BLOCKCHAIN_CURRENCY`
- `BLOCKCHAIN_RPC_URL`
- `BLOCKCHAIN_MERCHANT_ADDRESS`
- `BLOCKCHAIN_MIN_CONFIRMATIONS`
- `BLOCKCHAIN_PRICE_INR_PER_TOKEN`

### Startup admin

- `DJANGO_SUPERUSER_USERNAME`
- `DJANGO_SUPERUSER_PASSWORD`

Do not put a superuser password in source control or in `Bren.md`.

## 8. Main user workflows

### 8.1 Browse auctions

1. Visitor opens `/`.
2. `auctions.views.home` lists auction items ordered by ending time.
3. The page displays title, image, end time, starting price, highest bid, and
   links to view or list an item.
4. `/items/<id>/` displays the auction detail, pricing, timing, seats,
   delivery information, and recent bids.

### 8.2 Register, login, and verification

1. `/register/` creates a Django user and `UserProfile`.
2. Registration collects username, email, password, phone, and location.
3. Email verification link and a six-digit OTP are prepared.
4. `/verify/` handles verification and resend actions.
5. `/login/`, `/logout/`, and `/history/` handle authentication/history.
6. Existing code does not consistently enforce verified email/phone before all
   listing, booking, bidding, or payment actions. Treat this as a product
   security gap, not an assumed guarantee.

### 8.3 Seller creates an auction

1. Authenticated user opens `/items/new/`.
2. The form accepts title, description, optional image, seller pickup address,
   city, PIN, delivery mode/charges, starting price, optional buy-now price,
   start/end times, and seat limit.
3. Form validation checks date order/future end, positive prices, buy-now
   relationship, and PIN shape.
4. The owner is automatically added as an auction participant.
5. There is currently no complete edit/delete listing workflow.

### 8.4 Book a seat and join the call

1. A non-owner can book a seat through the ₹5 seat-payment flow.
2. Payment can use Google Pay/PhonePe UX, bank/manual flow, or configured
   blockchain flow depending on the page.
3. A successful payment activates the participant and generates a booking code.
4. `/join/` verifies the code.
5. The owner can start the preview and call, and can save a Google Meet URL
   restricted to `meet.google.com`.
6. The call page is a Google Meet link plus activity/presence polling; it is not
   an embedded video meeting product.

### 8.5 Wallet and payments

1. `/wallet/` shows wallet balance, available balance after holds, history,
   payment methods, and linked bank accounts.
2. `/wallet/recharge/` starts wallet recharge.
3. Supported paths include Google Pay/PhonePe UPI UX, manual bank/UPI with UTR,
   and optional blockchain transfer verification.
4. `Payment.processed_at` is intended to make post-payment effects idempotent.
5. Wallet holds reserve funds for bids, release losing holds, and consume the
   winning hold at settlement.

### 8.6 Bid

A bidder must generally:

- be authenticated
- not be the auction owner
- be booked and not unbooked
- have no unpaid penalty
- be inside the active time window
- satisfy participant/seat rules
- have enough available wallet funds

The bid path uses database transactions/locks, creates a `Bid`, reserves or
updates a `WalletHold`, releases the previous leader's hold, records audit
transactions, and appends a proof-of-work-style `LedgerBlock`. It then attempts
to broadcast a `new_bid` Channels event.

### 8.7 Live auction updates

- WebSocket path: `/ws/auctions/<item_id>/`
- Browser bid data path: `/items/<id>/bids.json`
- `AuctionConsumer` joins an item group and receives server bid events.
- Redis is needed for reliable shared events across multiple production
  instances. Without `REDIS_URL`, settings use an in-memory layer suitable only
  for limited/single-process use.

### 8.8 Settle and deliver

1. Owner/staff can settle an ended auction through `/items/<id>/settle/` or the
   `settle_auctions` command.
2. The highest active bid becomes a paid `Order`.
3. Winning wallet hold is consumed and losing holds are released.
4. The winner can submit delivery details through `/items/<id>/delivery/`.
5. There is no complete seller fulfillment/shipping/refund/dispute workflow.
6. Settlement does not currently perform an actual seller bank payout.

## 9. Database models

The schema source of truth is `auctions/models.py` plus migrations:
`auctions/migrations/0001_initial.py` through `0016_add_delivery_pickup_fields.py`.

- `AuctionItem` — listing owner, title, description, image, pickup/delivery,
  prices, schedule, seats, active/settled state, call/Meet metadata
- `Bid` — bidder, amount, active state, unique transaction ID
- `AuctionParticipant` — booking/payment/code/preview/presence/penalty state
- `Payment` — buyer, recipient, amount, purpose, provider, status, manual
  payment fields, blockchain fields, processed timestamp
- `Order` — buyer, item, amount, status, delivery details
- `LedgerBlock` — simple audit-style hash chain/proof-of-work records
- `UserProfile` — phone, location, email/phone verification, UPI and bank fields,
  auto-debit consent
- `Wallet` — INR balance
- `BankAccount` — bank details for a user
- `WalletTransaction` — credit/debit/hold audit entries
- `WalletHold` — active/released/consumed bid reserve with unique active hold
- `Transaction` — unified audit log
- `DataBackup` — backup tracking
- `DataRetentionPolicy` — retention rules
- `UserDataExport` — compliance export tracking

### Storage reality

- Default database is local `db.sqlite3`.
- Default uploaded files are local under `media/`.
- Both are acceptable for development but are not enough for a durable
  multi-instance production deployment.
- PythonAnywhere deployment needs a deliberate persistent database and media
  plan before production data is moved.

## 10. URL map

Project-level routes in `auction_site/urls.py`:

- `/admin/`
- `/robots.txt`
- `/sitemap.xml`
- `/favicon.ico`
- `/media/...`
- all auction routes below

Auction routes in `auctions/urls.py`:

```text
/                         home
/index/                   index
/login/                   login
/logout/                  logout
/register/                register
/history/                 user history
/items/new/               create auction
/items/<id>/              auction detail
/items/<id>/bid/          place bid
/items/<id>/buy/          buy now
/payments/<id>/gpay/      Google Pay start
/payments/<id>/phonepe/  PhonePe start
/payments/<id>/callback/ payment callback
/payments/<id>/crypto/   crypto payment start
/payments/<id>/crypto/confirm/
/payments/<id>/bank/     manual bank payment start
/payments/<id>/bank/confirm/
/items/<id>/book/        book seat
/items/<id>/unbook/      cancel seat
/join/                    verify booking code
/items/<id>/preview/start/
/items/<id>/call/start/
/items/<id>/call/
/items/<id>/call/activity/
/items/<id>/bids.json    public bid JSON
/items/<id>/meet/        set Meet URL
/items/<id>/presence/    presence heartbeat
/items/<id>/penalty/pay/
/items/<id>/settle/
/items/<id>/delivery/
/verify/
/verify/resend-otp/
/verify/resend-email/
/wallet/
/wallet/recharge/
/wallet/payment-methods/
/wallet/bank/link/
/export-data/
```

## 11. Admin and operations

`auctions/admin.py` registers basic admin views for:

- AuctionItem
- Bid
- Payment
- LedgerBlock
- AuctionParticipant
- Order
- UserProfile
- Wallet
- WalletTransaction
- WalletHold

Django's built-in User admin is also available. `DataBackup`,
`DataRetentionPolicy`, and `UserDataExport` are not currently registered in the
admin.

Management commands:

- `settle_auctions.py` — settle ended active auctions; supports dry-run/limit
- `scheduled_backup.py` — backup policy-driven/full/incremental data and media
- `backup_user_data.py` — user/system backup helpers
- `restore_data.py` — partial JSON restore
- `setup_data_retention.py` — retention policy setup
- `run_settlements.sh` — shell wrapper for settlement scheduling

No scheduler is configured by default. Settlement and backups need manual
execution or an external cron/scheduler in production.

## 12. Changes already made

These are intentional completed repairs:

### Startup and Replit preview

- Replaced the broken nonexistent `app:app` startup target.
- Added a working Django/Daphne workflow.
- Made startup path-independent instead of hard-coding
  `/home/runner/workspace`.
- Made missing environment variables safe under `set -u`.
- Added migrations and static collection at startup.
- Added root artifact routing so the Django website is visible at `/`.
- Repointed the unused API artifact wrapper to the Django app on port 8000.
- Kept the mockup sandbox separate.

### Dependency and settings

- Cleaned duplicate requirements.
- Updated Django to compatible `5.2.17`.
- Required a configured `SECRET_KEY` or `SESSION_SECRET`.
- Defaulted DEBUG to false outside a Replit development preview.
- Added configurable hosts and CSRF trusted origins.
- Added proxy-aware HTTPS redirect, secure cookies, and HSTS defaults.
- Preserved a Replit proxy setup that does not create an SSL redirect loop.
- Kept Cloudinary, Redis, database, email, payment, and blockchain settings
  environment-driven.

### UI/resource cleanup

- Removed invalid favicon references that caused a browser 404.
- Confirmed homepage, login, registration, admin login, CSS, JavaScript, and
  favicon load successfully in the live Replit preview.

### Verification already completed

- `python3.11 manage.py check` passes.
- `python3.11 manage.py check --deploy` passes with no warnings in the verified
  environment.
- Migrations run successfully.
- Static files collect successfully.
- Daphne listens on port 8000.
- Live preview endpoints return HTTP 200 for `/`, `/login/`, `/register/`, and
  `/admin/login/`.

## 13. Known gaps and launch blockers

These are documented risks, not silently fixed:

### High priority security

- WebSocket consumer currently accepts sockets without strong item-level
  authorization.
- Several mutation routes are not consistently POST-only/CSRF-protected.
- Manual bank confirmation trusts a user-entered UTR without provider
  reconciliation.
- Payment callback authorization and idempotency need hardening.
- Blockchain confirmation flow needs strict merchant/payer/minimum-confirmation
  validation before applying payment effects.
- Sensitive bank, UPI, payment, and participant data is stored/displayed too
  broadly and is not consistently encrypted.
- Client-side bid/call rendering uses concatenated `innerHTML`; escape untrusted
  values before rendering.
- Call activity can expose booking codes to other call users.
- Seller pickup address and public bidder identities need an explicit privacy
  policy.

### Correctness and product gaps

- Winner payment links in `item_detail.html` point to a route that is not
  currently present in `auctions/urls.py`; winner payment flow needs a complete
  order-payment route.
- `export_user_data` currently calls `self.serialize_model_data` even though the
  serializer is not a method; the export endpoint is broken and broad.
- Wallet `auto_debit_consent` changes are not reliably persisted in the current
  update path.
- Buy-now does not fully enforce auction state, owner exclusion, duplicate
  purchase prevention, or finalization.
- Settlement can be duplicated under concurrent calls and is currently exposed
  as a mutating route that should be POST-only.
- Seller payout, fulfillment, shipment tracking, refund, dispute, and messaging
  are not implemented as complete workflows.
- Email/OTP failure is swallowed and console email is used without SMTP.
- There is no SMS provider.
- There is no scheduler configured for settlement or backups.
- Local SQLite/media are not durable production storage.
- In-memory Channels is not suitable for multi-instance live auctions.
- The proof-of-work ledger is an audit helper, not a secure blockchain.
- Backup encryption/restore behavior needs a security review before being called
  production-safe.

### Test coverage gaps

Current tests are narrow. They cover wallet hold balance behavior and bid
transaction ID generation. There are not yet comprehensive tests for:

- registration and verification
- authorization and admin permissions
- URL/template rendering
- listing validation
- booking and payment providers
- buy-now and settlement concurrency
- delivery and order states
- WebSocket authorization and reconnect behavior
- CSRF and XSS protections
- backup/export/restore
- production database/media behavior

## 14. Deployment plan

### Replit publishing

1. Run the checks in the verification section.
2. Confirm all required production secrets/configuration names are set without
   exposing their values.
3. Decide whether the production database is ready; do not rely on ephemeral
   SQLite for a serious live marketplace.
4. Confirm media storage and Redis requirements.
5. Publish through Replit's publishing UI. The agent may prepare and verify the
   configuration, but the user performs the final Publish action.
6. After publishing, use the deployment metadata/tooling to get the real
   `*.replit.app` URL. Never invent it from a development domain.
7. Test production HTTPS, auth, static files, media, payment callbacks,
   WebSockets, and database persistence.

### PythonAnywhere

1. Choose/configure a persistent production database.
2. Migrate schema deliberately; do not overwrite or discard auction data.
3. Configure persistent media storage and backups.
4. Use `auction_site.wsgi:application` for a WSGI web app, or a supported
   ASGI/WebSocket arrangement if live bidding is required.
5. Configure the domain in `ALLOWED_HOSTS` and
   `CSRF_TRUSTED_ORIGINS`.
6. Configure SMTP, payment provider verification, and any blockchain settings.
7. Run settlement/backups through a controlled scheduled task.
8. Test with staging data before moving real auction data.

## 15. Standard verification commands

Run from the repository root:

```bash
python3.11 manage.py check
python3.11 manage.py check --deploy
python3.11 manage.py migrate --noinput
python3.11 manage.py collectstatic --noinput
```

Start the local/Replit-style server:

```bash
bash start_django.sh
```

Useful read-only checks:

```bash
git status --short
find templates/auctions -maxdepth 1 -type f | sort
find auctions/migrations -maxdepth 1 -type f -name '*.py' | sort
```

Never run destructive database reset, broad migration reversal, production
restore, or data deletion as a routine verification step.

## 16. Future AI work checklist

Before implementation:

- Read `Bren.md`.
- Inspect `git status`.
- Identify the source-of-truth files for the requested behavior.
- Check whether the request is a bug fix, security fix, UI change, data change,
  deployment change, or new product feature.
- Preserve existing business rules unless the user changes them.
- Check whether the requested change touches money, identity, personal data,
  media, database schema, or live auction concurrency.

During implementation:

- Prefer small targeted edits.
- Keep secrets in environment tooling.
- Use Django transactions/locks for balance, hold, bid, payment, and settlement
  changes.
- Enforce authorization on every object-level action.
- Escape untrusted content in templates and JavaScript.
- Use POST + CSRF for mutations.
- Keep Replit artifact routing separate from auction domain logic.

After implementation:

- Run `manage.py check`.
- Run relevant tests.
- Run `manage.py check --deploy` for production/security changes.
- Restart the relevant workflow once after runtime/config changes.
- Check logs and test the affected HTTP/WebSocket flow.
- Update this file only if the change creates a durable project fact or changes
  one of the documented rules.

## 17. Current decision summary

- Django is the real application; do not replace it with the generic Node
  scaffold.
- SQLite/local media are development defaults, not the final production plan.
- Redis is optional in code but important for reliable multi-instance realtime
  auctions.
- Existing auction/payment behavior is preserved until explicitly redesigned.
- The preview routing problem was fixed through the Replit artifact wrapper.
- Production security checks currently pass in the verified environment.
- GitHub push and PythonAnywhere deployment are separate later operations and
  must be verified independently.