# Development notes

How the project is put together, and the rules I follow when changing it.
For running the app and trying it out, see [TESTING.md](TESTING.md).

## Commands

```bash
python -m venv myenv
myenv/bin/pip install -r requirements.txt
myenv/bin/python manage.py migrate
myenv/bin/python manage.py runserver        # Swagger docs at http://127.0.0.1:8000/api/docs/
myenv/bin/python manage.py test              # all tests (SQLite)
myenv/bin/python manage.py makemigrations --check --dry-run
DATABASE_URL=postgres://... myenv/bin/python manage.py test   # also runs the PostgreSQL-only tests
```

GitHub Actions (`.github/workflows/ci.yml`) runs the tests, the migrations check and
`pip-audit` on every push. Render runs `build.sh` and then gunicorn.

## How the apps fit together

| App | What it does |
| --- | --- |
| `users` | sign up, sign in with an emailed code, KYC documents, password change and reset, closing an account |
| `wallets` | one wallet per user, and `services.py`, the only code that changes balances |
| `transactions` | deposits (staff only), withdrawals, transfers and transaction history |
| `loans` | loan applications, staff approval and monthly payments (EMIs) |
| `analytics` | simple fraud rules that flag suspicious transactions for staff |

Things worth knowing:

- **Balances only change through `wallets/services.py`.** Use `lock_wallets`, `credit` and `debit`
  inside `transaction.atomic()`, and create a `Transaction` row for every change.
- **After creating a transaction, call `flag_transaction_safely(tx)`** so the fraud rules run.
- **KYC:** withdrawals and loans need `kyc_status == "verified"`. Transfers above
  `UNVERIFIED_TRANSFER_LIMIT` need it too.
- **Deposits are staff only** and need a unique `funding_reference`.
- **Sign in has two steps:** `/users/signin/` checks the password and emails a code,
  `/users/verify-signin-otp/` gives the tokens. Codes are stored in the `OTP` table (see `users/security.py`).
- **Lockout:** 5 wrong passwords lock the account for 15 minutes (`users/backends.py`).
- **Users are never deleted.** Closing an account removes personal details and deactivates it.
- **KYC files** are stored in `private_media/` and can only be downloaded through
  `/users/kyc/documents/<user_id>/<identity|address>/` by the owner or staff.
- **Rate limits** use the database cache in production so all workers share the counters.
- **Emails** on Render go through an email API (django-anymail), because the free plan blocks SMTP.

## Rules for changing the code

These come from the security review (see [review-notes.md](review-notes.md)). Each one is
there because the bug really happened once.

1. **Check who is allowed.** Being logged in is not the same as being allowed. Filter by
   the logged-in user, or use `IsAdminUser` for staff actions.
2. **Never trust values from the request to authorise things.** An amount, email or flag in
   the request body can't decide who gets money or who you are.
3. **Money changes go through `wallets/services.py` inside `transaction.atomic()`.** Never
   save a balance you worked out from an earlier read.
4. **Check-and-update must happen in one step.** For one-time things (codes, loan approval,
   EMI payment) use a conditional `UPDATE ... WHERE still_valid` and only continue if exactly
   one row changed, or lock the row with `select_for_update()` and check again.
5. **Fail closed.** No `except Exception: pass` around login, money or audit code. Log the
   error and return an error.
6. **Financial records are never deleted.** Foreign keys to users, loans and transactions use
   `on_delete=PROTECT`.
7. **Any code that changes a password must call `revoke_user_tokens(user)`.**
8. **No secrets in the code.** Never commit `.env`, `.dev_secret_key`, `db.sqlite3`, `media/`
   or `private_media/`.
9. **Private files** are only served through a view that checks owner or staff.
10. **Codes (OTPs):** make them with `secrets`, compare with `hmac.compare_digest`, limit
    guesses and how many can be sent, and check expiry every time.
11. **Every bug fix gets a test that fails without the fix.** For race conditions, write a
    "stale snapshot" test where another write happens between the read and the write
    (see `wallets/tests.py` and `loans/tests.py`).

## Test helpers

`utils/testing.py` has `make_user`, `make_staff`, `auth_client`, `balance_of` and
`last_emailed_code`. Tests that call rate-limited endpoints run `cache.clear()` in `setUp`.
