# Review Notes — Banking API

Source: 13 scanner findings (security) + manual review of the codebase (bugs, style, design, and 4 extra security issues).
Line numbers refer to the code **before** the fixes in this branch.

## Summary

| ID | Severity | Type | Location | Issue |
|---|---|---|---|---|
| S1 | High | Security | `transactions/views.py:53-63` | Customers credit their own wallet with any amount via `/transactions/deposit/` |
| S2 | High | Security | `users/views.py:378-379` | Access tokens survive password change / reset |
| S3 | High | Security | `users/views.py:438` | Self-delete cascades away loans, EMIs, transactions, fraud flags |
| S4 | Medium | Security | `loans/views.py:85-87` | Loan approval writes a stale wallet balance (race) |
| S5 | Medium | Security | `my_fintech_app/settings.py:34,129` | Fixed fallback `SECRET_KEY` lets anyone forge JWTs in debug |
| S6 | Medium | Security | `my_fintech_app/urls.py:41` | KYC documents served unauthenticated from `/media/` |
| S7 | Medium | Security | `transactions/models.py:28` | Deleting a receiver cascades into other users' transactions |
| S8 | Medium | Security | `transactions/views.py:205-223` | Transfers never reach the fraud scorer |
| S9 | Medium | Security | `users/views.py:255-256` | Sign-in OTP can be consumed twice concurrently |
| S10 | Medium | Security | `users/views.py:257-268` | Session OTP fallback is not bound to an account → log in as anyone |
| S11 | Medium | Security | `users/views.py:699-705` | Password-reset OTP has no attempt limit (brute force) |
| S12 | Medium | Security | `users/views.py:730-748` | Password reset ignores the recovery expiry |
| S13 | Medium | Security | `wallets/views.py:124` | Admin balance edit races transfers; audit record can silently fail |
| S14 | High | Security | `media/kyc_documents/*`, `db.sqlite3` | Real KYC images and the dev database are committed to git |
| S15 | High | Security | `loans/views.py:80-90` | Approving an already-approved loan credits the wallet again |
| S16 | Medium | Security | `loans/views.py:124-146` | EMI `is_paid` checked outside the lock → double payment |
| S17 | Low | Security | `users/views.py:53-54` | OTPs generated with `random` (not cryptographically secure) |
| B1 | Medium | Bug | `wallets/views.py:2` | `logger` imported from `asyncio.log` instead of `logging.getLogger(__name__)` |
| B2 | Medium | Bug | `wallets/views.py:4` | `django.forms.ValidationError` raised inside DRF views → 500, not 400 |
| B3 | Medium | Bug | `transactions/views.py:236,292` | History filters `sender=user` only — recipients never see incoming transfers |
| B4 | Medium | Bug | `transactions/views.py:224-226` | `except Exception` returns 500 for every failure, hiding real errors |
| B5 | Low | Bug | `wallets/views.py:31,77,99` | `@extend_schema` decorates `get_object`/`perform_update`, not HTTP methods — docs silently lost |
| B6 | Low | Bug | `users/views.py:459,502` | `block_user` checks `role == "admin"`; everything else uses `is_staff` |
| B7 | Low | Bug | `users/views.py:646` | `send_mail(fail_silently=False)` in an anonymous endpoint → 500 if SMTP is down |
| ST1 | Low | Style | many | Unused imports, imports inside functions (`users/views.py:63,82,199,248`) |
| ST2 | Low | Style | repo root | `requirement.txt` and `requirements.txt` both exist (fixed 2026-10-15: stale `requirement.txt` removed) |
| ST3 | Low | Style | `loans/models.py` | Tabs instead of spaces |
| ST4 | Low | Style | `analytics/utils.py:7` | camelCase function name `simple_flagTransaction` |
| ST5 | Low | Style | `users/signals.py:13`, logging calls | `print()` in signals; f-strings in `logger.*` calls |
| ST6 | Low | Style | many | Commented-out code blocks, "tests intentionally removed" files |
| ST7 | Low | Style | `transactions/views.py:46,103,173` | `amount <= 0` re-checked after the serializer already validated it |
| ST8 | Low | Style | repo | `__pycache__/*.pyc` committed |
| D1 | High | Design | transactions, loans, wallets | No single owner for money movement: 6 balance writers, 3 locking strategies |
| D2 | High | Design | all models | `CASCADE` on financial records + hard deletes |
| D3 | Medium | Design | `users/views.py` | Two auth-state stores (Django session + JWT) in a "stateless" API |
| D4 | Medium | Design | users | Two definitions of admin (`role` vs `is_staff`) |
| D5 | Medium | Design | transactions | Fraud monitoring wired ad hoc in each view (and forgotten in one) |
| D6 | High | Design | all apps | No automated tests |

## By severity

**High:** S1, S2, S3, S14, S15, D1, D2, D6
**Medium:** S4–S13, S16, B1–B4, D3, D4, D5
**Low:** S17, B5–B7, ST1–ST8

## By type

### Security (S1–S17)

The scanner found S1–S13. The manual review added S14–S17:

- **S14:** six KYC images under `media/kyc_documents/` and `db.sqlite3` are tracked in git, so identity documents and user data sit in the repo history.
- **S15:** `admin_approve_loan` never checks `status == "pending"`, so an approved loan can be approved again and paid out twice.
- **S16:** `EMIPayAPIView` reads `emi.is_paid` before taking the lock, so two concurrent requests can both pay the same EMI.
- **S17:** `generate_otp` uses `random.randint`, which is predictable. Use `secrets` instead.

**The underlying mistake:** the code trusts the happy path. It shows up in four forms:
1. **Authenticated is treated as authorized.** If a request has a valid token, the code assumes it can do anything, so customers can deposit, delete their debt, or read KYC files.
2. **Client input is treated as authority.** The deposit amount, the email in the OTP check, and the "verified" flag in the session are all believed without proof.
3. **Fallbacks fail open.** When something goes wrong (`except Exception:`), the code takes a *weaker* path: a session OTP, a hard-coded secret key, skipping the audit record, skipping fraud checks. Security code must fail **closed**.
4. **Check-then-act in separate steps.** The code reads a value, checks it, then writes it in a later statement. Another request can change it in between (OTP use, loan approval, EMI pay, balances). The check and the write must be one atomic database operation.

### Bugs (B1–B7)

**The underlying mistake:** patterns get copied without checking what they do. B1 came from an IDE auto-import and B2 imports the wrong `ValidationError`. B5 puts a decorator on the wrong method. B4 is a broad `except` that turns every failure into the same 500, so these bugs never surfaced. Nothing caught them because there are no tests: each one fails loudly in a 3-line test.

### Style (ST1–ST8)

**The underlying mistake:** scaffolding stays behind after a feature works. That includes debug `print`s, commented-out code, duplicate requirement files, compiled files, and defensive checks repeated in two places. None of these is dangerous alone, but together they hide the lines that matter. For example, in a 30-line view it is easy to miss that the fraud check is the one call that's absent.

### Design (D1–D6)

**The underlying mistake:** business rules live in views instead of in one place that enforces them. Each view re-implements "change a balance" its own way:
- One locks the `User` row.
- One locks the `Wallet` row.
- Two lock nothing.
- One remembers fraud checks, and one forgets them.

Deleting rows was never thought through for money data, so Django's default `CASCADE` decided the policy. The fix is a small service layer (`wallets/services.py`) that every money path must go through, plus `PROTECT` on financial foreign keys and tests that pin the invariants.

## Security fixes applied (this branch)

| ID | Why it matters | Fix | Regression test |
|---|---|---|---|
| S1 | Money from nothing | Deposit is staff-only and needs a unique `funding_reference`. A reused reference gets 409 | `transactions/tests.py::DepositAuthorizationTests` |
| S2 | A stolen token survives recovery | `CHECK_REVOKE_TOKEN`, plus blacklisting outstanding refresh tokens on change and reset | `users/tests.py::TokenRevocationTests` |
| S3, S7 | Debt and audit trail erased | Soft delete + anonymise; returns 409 while obligations remain; `PROTECT` on financial FKs | `users/tests.py::AccountDeletionTests` |
| S4, S15 | Stale write restores spent money; double payout | Locked `pending` check + `F()` credit inside `atomic()` | `loans/tests.py::LoanApprovalTests` |
| S5 | Forged JWTs | No literal fallback; a random dev key is persisted to the gitignored `.dev_secret_key` | `users/tests.py::SigningKeyTests` |
| S6, S14 | KYC leak | No public media route; private storage; owner/staff-only download view; media and db untracked | `users/tests.py::KYCDocumentAccessTests` |
| S8 | Fraud is invisible | `flag_transaction_safely` on every money path; failures recorded as `monitoring_failed` | `transactions/tests.py::TransferMonitoringTests` |
| S9 | OTP reused concurrently | Conditional `UPDATE … WHERE is_used=False` consumption | `users/tests.py::SigninOTPTests` |
| S10 | Log in as the victim | Session fallback removed; persistence failure → 503 | `users/tests.py::SigninOTPTests` |
| S11, S17 | OTP brute force | 5-attempt cap, issuance budget per account, `ScopedRateThrottle`, `secrets` | `users/tests.py::PasswordResetTests` |
| S12 | Expired grant still works | Reset consumes the verified OTP row with `expires_at__gt=now` | `users/tests.py::PasswordResetTests` |
| S13, S16 | Lost updates | Every balance write is an `F()` update through `wallets/services.py`; the audit record is written in the same transaction | `wallets/tests.py`, `loans/tests.py::EMIPayTests` |

## Still to do (owner decision)

- **Rotate the key:** rotate the `SECRET_KEY` on Render, and on any instance that ever ran with the old fallback key.

### Done since
- **Purge history (2026-10-14):** `media/` and `db.sqlite3` were removed from git history with `git filter-repo` and force-pushed. Clones made before that still have them.
- **Generic OTP endpoints (2026-10-15):** `send-otp/` and `verify-otp/` now use the DB-backed helpers (purpose `verify`), with the same single-use, 5-guess, issuance-cap and expiry rules. They return 503 if the email fails. Tests: `users.tests.GenericOTPTests`.
- **Hardening (2026-10-15):** with `DEBUG` off, the settings turn on `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT` (except `/health/`), secure session and CSRF cookies, and HSTS for 1 year. `check --deploy` is clean. Test: `users.tests.ProductionSecuritySettingsTests`.

## Behaviour changes to tell API clients about

- `POST /transactions/deposit/` is now **staff-only** and needs `user_id`, `amount` and `funding_reference`.
- Enabling `CHECK_REVOKE_TOKEN` invalidates every token issued before the deploy, so everyone signs in again once.
- `DELETE /users/delete/` closes the account (soft delete). It returns 409 while there are unpaid EMIs, a pending loan or a non-zero balance.
- KYC documents: download via `GET /users/kyc/documents/<user_id>/<identity|address>/`. `/media/` is no longer served.
- `signin`, `verify-signin-otp`, `request-password-reset`, `verify-password-reset-otp` and `reset-password` are rate-limited per IP (10/min). A challenge dies after 5 wrong guesses, and each account gets 3 codes per 15 minutes.

## Second review (2026-10-15): open findings N1–N18

This is a full re-read of every view, serializer, model, setting and deploy file, done after S1–S17 were fixed and deployed. Each fix must ship with a test that fails without it.

**Fixed:** N1–N18 (see "Fixes applied" below).

### High

| ID | Issue | Where | How it goes wrong | Suggested fix |
|---|---|---|---|---|
| N1 | Unlimited password guessing | `users/views.py` `signin`; `/admin/` login | `signin` has no throttle and no per-account lockout, so passwords can be guessed indefinitely. `/admin/` is the same, and a staff password found there gives full access with no emailed code. | Add a sign-in throttle per IP and per email, plus a DB-backed failure counter with a temporary lockout. Throttle `/admin/` login too (e.g. django-axes). |
| N2 | Rate limits bypassable by faking an IP header | `settings.py` `REST_FRAMEWORK` | `NUM_PROXIES` isn't set, so DRF identifies clients by the whole `X-Forwarded-For` header, which the client controls. A different fake value on each request starts a fresh `OTPRateThrottle` bucket. | Set `NUM_PROXIES` to Render's proxy count (likely 1; confirm from live request logs). Test that a spoofed header can't avoid the limit. |
| N3 | Loan amount and duration not validated | `loans/serializers.py` `LoanApplyRequestSerializer`; `wallets/services.py` | Apply for `amount=-500` and have it approved. Disbursal debits the wallet and the EMIs are negative. Paying one calls `debit(-x)`, the `balance__gte=-x` guard always passes, and the balance goes up: money is created. `duration_months=10**8` makes approval try to create 100M EMI rows. | Require `amount > 0`, set a maximum amount and `1 <= duration_months <= 60`. Make `credit()`/`debit()` raise `ValueError` for `amount <= 0` as a second line of defence. |

### Medium

| ID | Issue | Where | How it goes wrong | Suggested fix |
|---|---|---|---|---|
| N4 | Staff can set any balance | `wallets/views.py` `WalletAdminUpdateAPIView` (`/wallets/admin/update/<pk>/`) | Any staff user can set any balance, with no funding reference, no reason and no fraud flag. This bypasses the referenced, staff-only deposit control (S1), so one insider can create money. | Remove the endpoint, or require `reason` and a unique `funding_reference`, use `credit`/`debit`, and call `flag_transaction_safely`. |
| N5 | Audit trail doesn't record who acted | `transactions/models.py`, `loans/models.py` | Deposits, balance adjustments and loan decisions name the staff member only in free-text `description`, or not at all. | Add a `Transaction.created_by` field and `LoanApplication.decided_by` (FK to user, `PROTECT`), set by the views. |
| N6 | BVN/phone enumeration; BVN exposed | `users/serializers.py` `UserSerializer.validate`, `UserProfileSerializer` | Sign-up answers "A user with this BVN already exists", so anyone can test whether a BVN is registered. A duplicate `phone_number` isn't checked and fails with an unhandled database error (500), which leaks the same thing. BVN is stored in plain text and returned in full by `/users/me/`. | Return a generic error and catch the database error. Show only the last 4 BVN digits. Consider encrypting BVN at rest. |
| N7 | Sign-up not rate limited | `users/views.py` `signup` | Anyone can script bulk account creation; each account triggers a welcome email to an address the attacker picks. This burns Brevo quota and sender reputation. | Add a per-IP sign-up throttle. Optionally verify the email before sending anything else. |
| N8 | KYC never enforced | `users/views.py` KYC views; transactions/loans views | Transfers, withdrawals and loans all work without KYC. Staff can approve KYC with no documents uploaded. Re-uploading after approval sets `kyc_status="pending"` but leaves `kyc_approved=True`. Replaced files are never deleted. | Require `kyc_status == "verified"` for loans and withdrawals (and transfers above a limit). Refuse approval without documents. Reset `kyc_approved` on re-upload and delete the replaced files. |
| N9 | Account closure race; closed accounts can be reopened | `users/views.py` `delete_user`, `unblock_user` | The balance and loan checks run without a lock, so an incoming transfer or loan approval that commits between the check and deactivation leaves money in a closed account. `unblock_user` can reactivate an anonymised, closed account. | Lock the wallet with `lock_wallets` and re-check inside one `atomic()` block. Refuse to unblock closed accounts (e.g. a `closed_at` field). |
| N10 | Long-lived tokens | `settings.py` `SIMPLE_JWT` | A stolen access token works for 24 hours. Refresh tokens (7 days) aren't rotated, and no refresh endpoint is mounted. | Cut access tokens to 15 minutes, mount `TokenRefreshView`, and enable `ROTATE_REFRESH_TOKENS` and `BLACKLIST_AFTER_ROTATION`. |
| N11 | Transfers reveal which emails have accounts | `transactions/serializers.py` `validate_receiver_email` | Any logged-in user can test unlimited emails ("Receiver with this email does not exist"). The check includes closed accounts. | Throttle transfers per user. Use one error for every receiver problem. |

### Low / hardening

| ID | Issue | Where | Suggested fix |
|---|---|---|---|
| N12 | Emails are case-sensitive, so `A@x.com` and `a@x.com` can be two accounts (look-alike accounts, misdirected transfers) | `users/serializers.py`, `signin`, transfer lookup | Lowercase emails on save and add a case-insensitive unique constraint (`Lower("email")`). |
| N13 | Swagger and the API schema are public in production | `my_fintech_app/urls.py` | Serve them only when `DEBUG` is on, or only to staff. |
| N14 | CORS settings do nothing (`corsheaders` isn't installed); `CORS_ALLOW_ALL_ORIGINS=True` would be dangerous if someone installed it | `settings.py` | Delete them, or install corsheaders with an explicit origin list. |
| N15 | Bad input causes 500s: non-numeric `loan_id`, bad `from_date`/`to_date`, duplicate phone | `loans/views.py` `admin_approve_loan`, `analytics/views.py`, sign-up | Validate with serializers and return 400. |
| N16 | `logout` catches a bare `Exception` and doesn't check that the token belongs to the caller | `users/views.py` `logout_view` | Catch specific errors and check `token["user_id"] == request.user.pk`. |
| N17 | Welcome email hard-codes its sender and a `localhost:3000` link | `users/signals.py` | Use `DEFAULT_FROM_EMAIL` and a `FRONTEND_URL` setting. |
| N18 | Nothing checks dependencies for known vulnerabilities | `requirements.txt` | Run `pip-audit` (e.g. in CI). |

Still open from the first review: rotate `SECRET_KEY` on Render (owner action).

### Fixes applied (N1–N18)

| ID | Fix | Tests |
|---|---|---|
| N1 | `users.backends.LockoutModelBackend` is the only auth backend, so it covers both API sign-in and `/admin/` login. After 5 wrong passwords the account is locked for 15 minutes; even the right password is refused, with the same answer as a wrong one. The counter lives on `User` (`failed_signin_attempts`, `signin_locked_until`) and is updated with `F()`. A successful password reset clears the lock. `signin` also uses `OTPRateThrottle` (10/min per IP). | `users.tests.SigninLockoutTests` |
| N2 | `REST_FRAMEWORK["NUM_PROXIES"]` (env `NUM_PROXIES`, default 1): throttles use the address Render appends, not the client-supplied part of `X-Forwarded-For`. If Render ever adds a hop, set `NUM_PROXIES` accordingly. | `users.tests.ThrottleIdentityTests` |
| N3 | Loan applications need `0.01 ≤ amount ≤ 1,000,000` and `1 ≤ duration_months ≤ 60`. Approval re-checks this for older applications. `wallets.services.credit`/`debit` raise `ValueError` for amounts ≤ 0. | `loans.tests.LoanLimitsTests`, `wallets.tests.NonPositiveAmountTests` |
| N4 | `PATCH/PUT /wallets/admin/update/<pk>/` requires `reason` and a unique `funding_reference` (PATCH can't skip them). It moves money through `credit`/`debit`, records the staff member, and is fraud-checked. | `wallets.tests.AdminWalletAdjustmentTests` |
| N5 | `Transaction.created_by` (deposits, adjustments, loan payouts) and `LoanApplication.decided_by` / `decided_at` (approve and reject), all `PROTECT`. | `transactions.tests.StaffAuditTests`, `loans.tests.LoanGovernanceTests`, `wallets.tests.AdminWalletAdjustmentTests` |
| N6 | A taken BVN or phone number gets one generic sign-up error (DRF's per-field unique validators are removed for those fields). A race that reaches the DB unique constraint returns 400, not 500. BVN must be 11 digits. `/users/me/` returns `*******1234`. | `users.tests.SignupPrivacyTests` |
| N7 | `SignupRateThrottle`: 5 sign-ups per hour per IP. | `users.tests.SignupPrivacyTests` |
| N8 | `users.permissions.IsKYCVerified` gates loan applications and withdrawals. Transfers above `UNVERIFIED_TRANSFER_LIMIT` (default 5,000) need verified KYC. Approval is refused without both documents. Re-uploading resets `kyc_status`/`kyc_approved` and deletes the old files. | `users.tests.KYCReviewTests`, `transactions.tests.KYCTransactionRulesTests`, `loans.tests.LoanGovernanceTests` |
| N9 | `delete_user` does its checks and the closure under `lock_wallets`. Transfers, deposits and loan payouts re-check that the receiver is active after taking the lock. New `User.closed_at`; `unblock_user` refuses closed accounts. | `users.tests.AccountClosureRaceTests`, `transactions.tests.ReceiverPrivacyAndClosureTests`, `loans.tests.LoanGovernanceTests` |
| N10 | Access tokens last 15 minutes. `POST /users/token/refresh/` returns a new access and refresh token; the old refresh token is blacklisted. | `users.tests.TokenLifetimeTests` |
| N11 | Unknown, closed and blocked receivers all get "Transfer could not be completed. Check the receiver's email." Transfers are limited to 30 per hour per user. | `transactions.tests.ReceiverPrivacyAndClosureTests` |
| N12 | `User.save()` lowercases emails; lookups use `email__iexact`; DB constraint `user_email_ci_unique` on `Lower(email)`. Migration 0011 lowercases existing emails and stops with a message if two differ only by case. | `users.tests.EmailCaseTests` |
| N13 | Swagger and the schema are mounted only when `API_DOCS_PUBLIC` is true (default: same as `DEBUG`). | `users.tests.APIDocsVisibilityTests` |
| N14 | Removed the unused CORS settings. If a browser frontend on another origin is added, install django-cors-headers with an explicit `CORS_ALLOWED_ORIGINS`. | — |
| N15 | `admin_approve_loan` validates input with its serializer; the analytics filters return 400 on bad values (phone duplicates: N6). | `loans.tests.LoanAdminInputTests`, `analytics.tests.FlaggedFilterValidationTests` |
| N16 | `logout` catches only `TokenError` and refuses another user's refresh token. | `users.tests.LogoutOwnershipTests` |
| N17 | Welcome email uses `DEFAULT_FROM_EMAIL`; the button links to `FRONTEND_URL` and is hidden when that's unset. | `users.tests.WelcomeEmailTests` |
| N18 | Upgraded Django 6.0.8, DRF 3.17.2, Pillow 12.3.0, PyJWT 2.15.0 and sqlparse 0.6.0 (pip-audit: no known vulnerabilities). `.github/workflows/ci.yml` runs the tests, the migration check and `pip-audit` on every push. | CI |

Also fixed while here: `analytics/` had no `__init__.py`, so the full test run silently skipped its tests.
- (2026-10-15) Emails are case-insensitive and stored lowercase.
- (2026-10-15) Swagger (`/api/docs/`) is off in production unless `API_DOCS_PUBLIC=true`.
- (2026-10-15) `logout` only accepts your own refresh token.
