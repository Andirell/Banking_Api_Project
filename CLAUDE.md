# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Django 6 + Django REST Framework banking API with JWT auth (simplejwt), deployed to Render. It has five apps: `users` (auth, OTP, KYC), `wallets`, `transactions`, `loans` (applications and EMIs), and `analytics` (fraud flags). Swagger UI is at `/api/docs/`. Known issues and their fixes are recorded in `review-notes.md`; findings from the second review are N1–N18 there (all fixed).

## Commands

The virtualenv is `myenv/` (Python 3.14). Use `myenv/bin/python` directly.

```bash
myenv/bin/pip install -r requirements.txt
myenv/bin/python manage.py migrate
myenv/bin/python manage.py runserver                 # Swagger at http://127.0.0.1:8000/api/docs/
myenv/bin/python manage.py test                      # whole suite (SQLite)
myenv/bin/python manage.py test users.tests.PasswordResetTests.test_verified_grant_expires   # single test
myenv/bin/python manage.py makemigrations --check --dry-run
DATABASE_URL=postgres://... myenv/bin/python manage.py test   # also runs the PostgreSQL-only race tests
```

There is no linter configured. CI (`.github/workflows/ci.yml`) runs the tests, `makemigrations --check` and `pip-audit -r requirements.txt` on every push; keep pinned versions free of known vulnerabilities. Render runs `build.sh` (pip install, collectstatic, migrate, createcachetable), then gunicorn with uvicorn workers on `my_fintech_app.asgi`.

## Configuration

`my_fintech_app/settings.py` loads `.env` via python-dotenv:
- **Database:** `DATABASE_URL` switches from SQLite to Postgres through `dj-database-url`.
- **Debug:** `DEBUG` defaults to on unless `RENDER` is set.
- **Secret key:** `SECRET_KEY` is resolved by `my_fintech_app/secret_key.py`. Production must set it. Debug runs generate a key and persist it to the gitignored `.dev_secret_key`. The key also signs JWTs.
- **Email:** the local `.env` points `EMAIL_BACKEND` at real Gmail SMTP. Override it with `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend` for manual testing. Creating a user fires a welcome email from `users/signals.py`, and sign-in emails an OTP.
- **Email on Render:** the free plan blocks outbound SMTP (ports 25/465/587), so production sends through an HTTP API via django-anymail. Set `EMAIL_BACKEND=anymail.backends.<provider>.EmailBackend` plus `ANYMAIL_*` env vars (e.g. `ANYMAIL_BREVO_API_KEY`). `EMAIL_TIMEOUT` (default 10s) stops an unreachable mail server from hanging requests. A failed welcome email is only logged; a failed sign-in OTP email returns 503.
- **Other settings:** `FRONTEND_URL` (links in emails; none when empty), `API_DOCS_PUBLIC` (Swagger/schema; defaults to `DEBUG`), `UNVERIFIED_TRANSFER_LIMIT`. The full variable list is in `README.md`.
- **Emails are case-insensitive:** stored lowercase by `User.save()`, unique on `Lower(email)`; look users up with `email__iexact`.
- **Rate limits:** sign-in and the anonymous OTP endpoints use `users.throttles.OTPRateThrottle` (`otp`), sign-up uses `SignupRateThrottle` (`signup`), and transfers use `TransferRateThrottle` (`transfer`). Clients are identified by the 3rd-from-last `X-Forwarded-For` entry (`NUM_PROXIES`, default 3: Render's chain is real client, Cloudflare edge, Render load balancer). In production the counters live in the database cache (`django_cache` table) so all gunicorn workers share them; locally they're in memory. Tests that hit throttled endpoints call `cache.clear()` in `setUp`.
- **Tokens:** access tokens last 15 minutes; refresh at `POST /users/token/refresh/` (rotating, single use).

## Architecture

- **Money movement goes through `wallets/services.py`.** Use `lock_wallets(*user_ids)` (row locks in pk order), `credit` and `debit` (F() updates; amounts must be positive; `debit` raises `InsufficientFunds`). The views for deposit, withdraw, transfer, EMI pay, loan approval and admin adjustment all call these inside `transaction.atomic()`. Every balance change also creates a `transactions.Transaction` row as the ledger entry.
- **KYC gates money out.** `users.permissions.IsKYCVerified` protects loan applications and withdrawals; transfers above `settings.UNVERIFIED_TRANSFER_LIMIT` need `kyc_status == "verified"`. Test users from `make_user` are verified by default; pass `kyc_status="pending"` to test the gate.
- **Staff actions are attributed.** Set `Transaction.created_by` for staff-recorded money movements and `LoanApplication.decided_by`/`decided_at` for loan decisions.
- **Deposits are staff-only.** `POST /transactions/deposit/` takes `user_id`, `amount` and a unique `funding_reference`. Customers cannot create balance.
- **Fraud monitoring:** after creating a Transaction, call `analytics.utils.flag_transaction_safely(tx)`. It runs `simple_flagTransaction` in a savepoint and records a `monitoring_failed` flag if scoring errors. Staff read the flags at `/analytics/flagged-transactions/`.
- **Auth flow:** `signin` checks the password (through `users.backends.LockoutModelBackend`, which locks an account for 15 minutes after 5 wrong passwords, admin login included) and emails an OTP. `verify-signin-otp` returns the JWT pair. OTPs live in the `users.OTP` table, keyed by user and `purpose` (`signin` / `password_reset`). `users/security.py` holds `issue_otp` (per-account issuance budget), `check_otp` (5-guess cap), `consume_otp` (conditional single-use UPDATE) and `revoke_user_tokens`. Password reset keeps only the verified OTP id in the Django session. `SIMPLE_JWT["CHECK_REVOKE_TOKEN"]` invalidates access tokens when the password changes.
- **Users are never hard-deleted.** `DELETE /users/delete/` refuses while there are unpaid EMIs, a pending loan or a non-zero balance. Otherwise it anonymises the account and deactivates it. Financial foreign keys (`Transaction.sender/receiver`, `LoanApplication.user`, `EMI.loan`, `Wallet.user`, `SuspiciousActivity.transaction`) are `PROTECT`.
- **KYC files** use `users.storage.PrivateMediaStorage` under `PRIVATE_MEDIA_ROOT` (`private_media/`). They have no URL and are served only by `GET /users/kyc/documents/<user_id>/<identity|address>/`, to the owner or staff. No media route is mounted in `urls.py`.
- **Admin:** "admin" means `is_staff` (`IsAdminUser`). The exceptions are `block_user` and `unblock_user`, which still check `role == "admin"` (see review-notes B6).
- **Wallets:** a wallet is created for each user by a `post_save` signal in `users/signals.py`.
- **Tests:** shared helpers live in `utils/testing.py` (`make_user`, `make_staff`, `auth_client`, `balance_of`, `last_emailed_code`).

## Rules (learned from the security review — see review-notes.md)

- Validate and authorize at the API boundary. Being authenticated is not authorization. Client-supplied values (amounts, emails, flags) never authorize money movement or identity on their own.
- Every balance change goes through `wallets/services.py` inside `transaction.atomic()`. Never `save()` a balance computed from an earlier read.
- Check-then-act on one-time state (OTPs, loan approval, EMI payment) must be a single conditional `UPDATE … WHERE <still valid>` acted on only when exactly one row changed, or a locked re-check.
- Fail closed. Never use `except Exception: pass` (or a weaker fallback path) around auth, money or audit code. Log the error and return an error, or record the failure somewhere staff can see it.
- Financial records are never deleted or cascaded. New foreign keys to users, loans or transactions use `PROTECT`, and account removal is soft delete.
- Any code that changes a password must call `revoke_user_tokens(user)`.
- No literal or fallback secrets. Never commit `.env`, `.dev_secret_key`, `db.sqlite3`, `media/` or `private_media/`.
- Private files are served only through a view that checks ownership or staff access, never through a static or media route.
- OTPs: generate with `secrets`, compare with `hmac.compare_digest`, cap attempts per challenge and issuance per account in the DB, and check expiry at every use, including the final consuming step.
- Every bug fix ships with a test that fails without the fix. Race conditions get a "stale snapshot" test, where a competing write commits between the read and the write (see `wallets/tests.py`, `loans/tests.py`).
