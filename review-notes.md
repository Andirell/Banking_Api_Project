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
| ST2 | Low | Style | repo root | `requirement.txt` and `requirements.txt` both exist |
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

- **Purge history:** `media/` and `db.sqlite3` are now untracked, but they remain in **git history**. Removing them needs `git filter-repo --path media --path db.sqlite3 --invert-paths` and a force-push to GitHub. Anyone who cloned the repo already has the files.
- **Rotate the key:** rotate the `SECRET_KEY` on Render, and on any instance that ever ran with the old fallback key.
- **Generic OTP endpoints:** `send-otp/` and `verify-otp/` still use session state. They don't grant anything today, but they should move to the DB-backed OTP helper before anything depends on them.
- **Hardening:** `check --deploy` still warns about `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT` and HSTS. The password-reset grant now lives in the session, so set the secure-cookie flags in production.

## Behaviour changes to tell API clients about

- `POST /transactions/deposit/` is now **staff-only** and needs `user_id`, `amount` and `funding_reference`.
- Enabling `CHECK_REVOKE_TOKEN` invalidates every token issued before the deploy, so everyone signs in again once.
- `DELETE /users/delete/` closes the account (soft delete). It returns 409 while there are unpaid EMIs, a pending loan or a non-zero balance.
- KYC documents: download via `GET /users/kyc/documents/<user_id>/<identity|address>/`. `/media/` is no longer served.
- `verify-signin-otp`, `request-password-reset`, `verify-password-reset-otp` and `reset-password` are rate-limited per IP (10/min). A challenge dies after 5 wrong guesses, and each account gets 3 codes per 15 minutes.
