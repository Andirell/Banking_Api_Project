# Testing guide and what's new

This guide covers what changed on 2026-10-14, how to run the app locally, and a step-by-step walkthrough that shows each change working. Every status code below was checked against a local run.
For the reasoning behind each change, see [`review-notes.md`](review-notes.md).

---

## 1. What's new

| Area | What changed | Why (finding) |
|---|---|---|
| Deposits | `POST /transactions/deposit/` is **staff-only**. It takes `user_id`, `amount` and a unique `funding_reference`, and a reused reference returns **409**. Customers get **403**. | S1: customers could create money |
| Sign-in | Password check, then a 6-digit code by email, then `verify-signin-otp` returns the JWTs. A code works **once**, dies after **5 wrong guesses**, and each account can request **3 codes per 15 min**. If the email can't be sent you get **503**, not a hang. | S9, S10 |
| Password reset | Request a code, verify it, then reset, all from the **same browser session** and within **5 minutes**. Resetting or changing a password **logs out every existing token**. | S2, S11, S12 |
| Rate limit | The anonymous OTP endpoints allow **10 requests per minute per IP**, after which they return 429. | S11 |
| Delete account | `DELETE /users/delete/` now **closes** the account: it anonymises it and deactivates it. It returns **409** while there are unpaid EMIs, a pending loan, or money left in the wallet. Transaction history is kept. | S3, S7 |
| KYC files | Files are private. Download them with `GET /users/kyc/documents/<user_id>/<identity\|address>/`, which works for the owner or staff only. `/media/...` no longer serves anything. | S6 |
| Transfers | Every transfer runs the fraud checks. Flags show up at `GET /analytics/flagged-transactions/` (staff only). | S8 |
| Loans and EMIs | A loan can only be approved once. An EMI can't be charged twice, even by two requests at the same moment. | S4, S15, S16 |
| Balances | Every balance change goes through `wallets/services.py`, with no lost updates when requests run at the same time. | S4, S13 |
| Secrets and ops | There's no hard-coded `SECRET_KEY`; debug runs generate a random `.dev_secret_key` instead. Email goes through django-anymail (Brevo) on Render. Render has a **new database that expires on 2026-11-13**. | S5 |

---

## 2. Start the app locally

Run these from the project folder (`FIntech_Program/`).

```bash
# 1. Install dependencies and update your database
myenv/bin/pip install -r requirements.txt
myenv/bin/python manage.py migrate

# 2. Create a staff/admin account (you only need to do this once)
myenv/bin/python manage.py createsuperuser
#    It asks for: Email, First name, Last name, Password

# 3. Start the server with emails printed in this terminal (no Gmail needed)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend myenv/bin/python manage.py runserver
```

The `EMAIL_BACKEND=...` prefix only applies to this run. Your `.env` is untouched.

Then open these pages:
- **Swagger (where you test):** http://127.0.0.1:8000/api/docs/
- **Django admin (to see the data):** http://127.0.0.1:8000/admin/. Log in with the superuser.

**Where the codes show up:** sign-in and reset codes are printed in the terminal running `runserver`. Look for these lines:
- `Use this OTP to complete sign in: 123456`
- `Your password reset OTP is 123456. It will expire in 5 minutes.`

New accounts also print a long HTML welcome email there. You can ignore it.

**Authorizing in Swagger:** after `verify-signin-otp`, copy the `access_token`. Click **Authorize** at the top of Swagger, paste the token (without the word `Bearer`), and click Authorize. To switch between customer and staff, click Authorize → Logout and paste the other token. Or use a second browser or private window for the staff user.

---

## 3. Guided walkthrough

Use **customer A** (`ada@example.com`), **customer B** (`ben@example.com`) and your **staff** superuser. The password used below is `Str0ng-Passw0rd!`.

### Step 1: Sign up two customers
`POST /users/signup/`
```json
{"first_name": "Ada", "last_name": "Customer", "email": "ada@example.com",
 "password": "Str0ng-Passw0rd!", "confirm_password": "Str0ng-Passw0rd!"}
```
- **Expect:** 201 `{"message": "sign up successful"}`. Repeat this for Ben.
- **Also try:** `"first_name": "ada"` returns 400 `Must start with a capital letter`.

### Step 2: Sign in with a one-time code
1. `POST /users/signin/` with `{"email": "ada@example.com", "password": "Str0ng-Passw0rd!"}` returns 200 `OTP sent...`.
2. Copy the code from the terminal.
3. `POST /users/verify-signin-otp/` with `{"email": "ada@example.com", "otp": "<code>"}` returns 200 with `access_token` and `refresh_token`.
4. **Send the same request again:** 400 `invalid or expired otp`.

**This proves** a code works once (S9). There's no session fallback that could log you into someone else's account (S10).

Sign in Ben and the staff user the same way, and keep all three tokens.

### Step 3: Only staff can add money
- **As Ada:** `POST /transactions/deposit/` with `{"amount": "1000"}` returns **403**.
- **As staff:** `POST /transactions/deposit/` with
  ```json
  {"user_id": <Ada's id>, "amount": "10000.00", "funding_reference": "BANK-0001"}
  ```
  returns **201**, with `balance` 10000. Get Ada's id from `GET /users/me/` as Ada, or from the admin.
- **Send the exact same request again:** **409** `This funding reference has already been used.`

**This proves** customers can't create money, and one real payment can't be credited twice (S1).

### Step 4: Transfer and fraud monitoring
- **As Ada:** `POST /transactions/send/` with `{"receiver_email": "ben@example.com", "amount": "6000.00"}` returns 201, with `balance` 4000.
- **As Ben:** `GET /wallets/details/` returns `{"balance": "6000.00"}`.
- **As staff:** `GET /analytics/flagged-transactions/` shows a flag with `"reason": "high_transfer_amount, new_receiver"`.
- **As Ada,** the same URL returns 403.

**This proves** transfers now go through the fraud checks (S8).

### Step 5: Overdraw protection
**As Ada:** `POST /transactions/withdraw/` with `{"amount": "999999.00"}` returns 400 `Insufficient funds.` The balance doesn't change.

### Step 6: Loans and EMIs
1. **As Ada:** `POST /loans/apply/` with `{"amount": "1200.00", "duration_months": 12, "reason": "laptop"}` returns 201 with `"status": "pending"`. Note the `id`.
2. **As staff:** `POST /loans/admin/approve/` with `{"loan_id": <id>, "action": "approve"}` returns **200** `loan approved`. Ada's balance goes up by 1200.
3. **Approve again:** **400** `loan is already approved`. No second payout (S15).
4. **As Ada:** `GET /loans/emis/` shows 12 installments of 100.00.
5. `POST /loans/emis/<emi id>/pay/` returns 200. **Pay the same EMI again:** 400 `EMI already paid.` (S16)

### Step 7: KYC documents stay private
1. **As Ada:** `POST /users/kyc/submit/` (Swagger shows file pickers) with any two images. You get 200.
2. `GET /users/kyc/documents/<Ada's id>/identity/` as different users:

   | Caller | Result |
   |---|---|
   | Ada | 200 (the image) |
   | Staff | 200 |
   | Ben | **404** `Document not found.` |
   | No token | 401 |

3. Open `http://127.0.0.1:8000/media/kyc_documents/<file>` in the browser and you get **404**.

Files are stored in `private_media/` and are never served directly (S6).

### Step 8: Password reset, and old tokens stop working
Swagger keeps one browser session, so do all three calls in the same tab:
1. `POST /users/request-password-reset/` with `{"email": "ada@example.com"}` returns 200. The message is the same whether or not the account exists.
2. `POST /users/verify-password-reset-otp/` with `{"email": "ada@example.com", "otp": "<code from terminal>"}` returns 200.
3. `POST /users/reset-password/` with `{"email": "ada@example.com", "new_password": "N3w-Str0ng-Pass!", "confirm_password": "N3w-Str0ng-Pass!"}` returns 200.

Then:
- **Ada's old token:** `GET /users/me/` returns **401** `The user's password has been changed.` (S2)
- **Signing in with the old password:** 401.
- **The same reset from a different session/browser** returns 400 `invalid password reset session`.
- **Waiting more than 5 minutes after verifying** before you reset also fails (S12).
- **Wrong guesses:** five wrong codes kill the challenge, so even the right code then fails (S11). If you try this by hand, **wait about 10 seconds between guesses**. Otherwise the 10-per-minute IP limit returns 429 first.

### Step 9: Closing an account keeps the history
- **As Ben** (still holding 6000): `DELETE /users/delete/` returns **409** `withdraw your remaining balance before closing the account`.
- `POST /transactions/withdraw/` with `{"amount": "6000.00"}`, then `DELETE /users/delete/`, returns 200 `account closed successfully`.
- **Ben's token:** 401 `User is inactive`.
- **In the admin,** Ben's user is renamed to `deleted-<id>@deleted.invalid`, and Ada's transfer to him **still exists** (S3, S7).

---

## 4. Automated tests

```bash
myenv/bin/python manage.py test                       # everything (about 20 s)
myenv/bin/python manage.py test users                 # one app
myenv/bin/python manage.py test users.tests.PasswordResetTests.test_verified_grant_expires   # one test
DATABASE_URL=postgres://user@host:port/db myenv/bin/python manage.py test   # also runs the real concurrency test
```

On SQLite you'll see `OK (skipped=1)`. The skipped test is the threaded race test, which needs Postgres.

| Test class | File | What it guards |
|---|---|---|
| `DepositAuthorizationTests` | `transactions/tests.py` | S1: staff-only deposits, unique funding reference |
| `TransferTests`, `TransferMonitoringTests` | `transactions/tests.py` | Transfers move money correctly; S8 fraud flags, including when the scorer crashes |
| `WalletServiceStaleSnapshotTests` | `wallets/tests.py` | S4/S13: balance writes never lose a concurrent change |
| `AdminWalletAdjustmentTests` | `wallets/tests.py` | S13: staff adjustment and its audit record commit together |
| `ConcurrentDebitTests` | `wallets/tests.py` | Real parallel withdrawals (Postgres only) |
| `LoanApprovalTests`, `EMIPayTests` | `loans/tests.py` | S4/S15 one-time approval; S16 EMI paid once |
| `TokenRevocationTests` | `users/tests.py` | S2: password change/reset kills old tokens |
| `SigningKeyTests` | `users/tests.py` | S5: no forgeable fallback key |
| `AccountDeletionTests` | `users/tests.py` | S3/S7: soft delete, history kept |
| `KYCDocumentAccessTests` | `users/tests.py` | S6: private storage, owner/staff only |
| `SigninOTPTests` | `users/tests.py` | S9/S10: single use, fail closed, attempt cap |
| `PasswordResetTests` | `users/tests.py` | S11/S12: attempt cap, issue limit, expiry, single use |
| `EmailFailureTests` | `users/tests.py` | Sign-up survives email failure; sign-in returns 503; HTTP email API works |

---

## 5. Testing the live app on Render

- **Swagger:** https://banking-api-project.onrender.com/api/docs/. The free instance sleeps when idle, so the first request can take about 50 seconds.
- **Sign-in codes** arrive by email only if Brevo is configured (`EMAIL_BACKEND`, `ANYMAIL_BREVO_API_KEY`, `DEFAULT_FROM_EMAIL` in Render → Environment).
- **There's no staff account in production yet,** and the free plan has no shell to create one. Test the staff steps (3, 4 flags, 6, 7 staff view) locally.
- **The database expires on 2026-11-13** (free plan). Upgrade it or create a new one before then.
- **Auto-deploy isn't firing right now.** After a push, start a deploy manually in the dashboard until the GitHub connection is fixed.

---

## 6. Troubleshooting

| You see | Meaning and fix |
|---|---|
| `429 Request was throttled` | More than 10 anonymous OTP requests in a minute from your IP. Wait a minute. |
| `503 could not send the sign-in code` | Email isn't working. Locally, start the server with the `EMAIL_BACKEND=...console...` prefix. On Render, check the Brevo variables. |
| `400 invalid or expired otp` | Wrong code, a code you already used, a code older than 5 minutes, or a newer code replaced it. Request a new one. |
| `400 invalid password reset session` | Reset must happen in the same browser session that verified the code. |
| `401 The user's password has been changed` | Expected after a password change or reset. Sign in again. |
| `401 User is inactive` | The account was closed or blocked. |
| `403` on deposit, flags or loan approval | That endpoint is staff-only. Use the superuser's token. |
| `ImproperlyConfigured: SECRET_KEY must be set` | You're running with `DEBUG=False` and no `SECRET_KEY`. Set it in `.env` or the environment. |
