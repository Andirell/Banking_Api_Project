---
name: backend
description: Safe patterns for this Django/DRF banking API. Use when adding or changing an endpoint, model, serializer, auth/OTP/password flow, wallet balance, transaction, loan/EMI, KYC upload, or account deletion, and when reviewing such changes.
---

# Backend changes in this repo

These patterns come from a security review of this codebase (`review-notes.md`). Each one prevents a bug that was actually shipped here.

## Pre-merge checklist

Answer every question before calling the change done:

1. **Who may do this?** Is the permission explicit (`IsAuthenticated` / `IsAdminUser` plus an ownership filter on the queryset)? Customers must not be able to create money, read other users' data, or erase obligations.
2. **What does the client control?** Does any request field (amount, email, id, flag) act as *authority*? Authority comes only from server-side state: the authenticated user, a verified OTP row, or a staff action with a unique external reference.
3. **Does a balance change?** It must go through `wallets.services` (`lock_wallets`, `credit`, `debit`) inside `transaction.atomic()`, together with its `Transaction` ledger row and `flag_transaction_safely(tx)`.
4. **Is there check-then-act?** That covers anything read, tested, then written: `is_used`, `is_paid`, `status == "pending"`, balance ≥ amount. Make the check part of the write: a conditional `UPDATE` or a `select_for_update()` re-check.
5. **What happens on failure?** No `except Exception: pass` and no fallback to a weaker mechanism. Return a 4xx/5xx, or record the failure where staff will see it.
6. **What happens on delete?** Financial foreign keys are `PROTECT`, and users are soft-deleted.
7. **Does a password change?** Call `revoke_user_tokens(user)`.
8. **Is anything private stored?** Use `PrivateMediaStorage`, served via an owner/staff-checking view.
9. **Is there a test that fails without the change?** For races, write a stale-snapshot test (below).

## Patterns

### Atomic one-time consumption (OTP, approval, EMI)
```python
# Exactly one concurrent caller gets 1; act only on that.
won = OTP.objects.filter(pk=otp.pk, is_used=False, expires_at__gt=timezone.now()).update(is_used=True) == 1
if not won:
    return Response({"error": "invalid or expired otp"}, status=400)
```
Do **not** read `obj.is_used`, then set `obj.is_used = True; obj.save()`.

### Balance changes
```python
from wallets.services import InsufficientFunds, credit, debit, lock_wallets

with db_transaction.atomic():
    sender_wallet, receiver_wallet = lock_wallets(sender.pk, receiver.pk)  # pk-ordered locks
    try:
        debit(sender_wallet, amount)          # UPDATE ... SET balance = balance - x WHERE balance >= x
    except InsufficientFunds:
        return Response({"error": "Insufficient funds."}, status=400)
    credit(receiver_wallet, amount)
    tx = Transaction.objects.create(...)
    flag_transaction_safely(tx)
```
If you return early after something has already been written in the block, call `db_transaction.set_rollback(True)` first.

### Locked state transition
```python
with db_transaction.atomic():
    loan = get_object_or_404(LoanApplication.objects.select_for_update(), pk=loan_id)
    if loan.status != "pending":
        return Response({"error": f"loan is already {loan.status}"}, status=400)
    ...
```

### Deleting things
- New foreign keys to `User`, `LoanApplication`, `Transaction`, `Wallet`: `on_delete=models.PROTECT`.
- Closing an account (see `users.views.delete_user`):
  1. Refuse with 409 while obligations remain.
  2. Anonymise the PII.
  3. Set `is_active=False` and `set_unusable_password()`.
  4. Call `revoke_user_tokens`.

### Auth and OTP
- Use `users.security`: `issue_otp(user, purpose)` → `check_otp(user, purpose, code)` → `consume_otp(otp.pk, ...)`.
- A challenge is bound to one user and one purpose. Never verify against session-only state, and never take identity from the request body after the check.
- Anonymous OTP endpoints get `@throttle_classes([OTPRateThrottle])`.
- Endpoints that reveal account existence (e.g. password reset) return the same response for unknown or rate-limited accounts.

### Secrets and files
- `SECRET_KEY` comes from `resolve_secret_key`. Never add a literal fallback.
- Uploads with personal data: `storage=private_kyc_storage`. Download through a view that checks `request.user.pk == owner_id or request.user.is_staff` and returns 404 otherwise.
- Never mount `static(MEDIA_URL, ...)`.

## Testing

- Helpers are in `utils/testing.py`: `make_user(email, balance=...)`, `make_staff()`, `auth_client(user)` → `(client, refresh)`, `balance_of(user)`, `last_emailed_code()`.
- Call `cache.clear()` in `setUp` for tests that hit throttled endpoints.
- **Stale-snapshot technique** (deterministic, runs on SQLite): commit the competing change *between* the code's read and its write, then assert both effects survive or the loser is rejected.
  ```python
  stale = Wallet.objects.get(user=u)
  Wallet.objects.filter(pk=stale.pk).update(balance=60)   # concurrent writer
  services.debit(stale, Decimal("30"))
  assert balance_of(u) == Decimal("30")                   # a read-modify-save would give 70
  ```
  For views, `patch` a function the view calls mid-flow (e.g. `OTP.is_expired`, `loans.views.lock_wallets`) with a side effect that performs the competing write.
- Real concurrency tests use `TransactionTestCase` with threads, behind `@skipUnless(connection.vendor == "postgresql", ...)`. Run them with `DATABASE_URL=postgres://...`.
- Run the suite with `myenv/bin/python manage.py test`, and check migrations with `makemigrations --check --dry-run`.
