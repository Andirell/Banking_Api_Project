# FinTech Digital Banking API (Learning Edition)

This repository is a compact FinTech backend built with Django + DRF. It focuses
on a small set of features useful for a capstone and for learning backend
concepts:

- Users (custom User model with email login)
- Wallets (per-user balances)
- Transactions (deposit, withdraw, transfer)
- Loans (apply, admin approve, EMI schedule generation)
- Analytics (simple fraud detection & flagged transactions)

Note about anti-fraud code: The historic placeholder app `anti_fraud/` was removed from the
project and is no longer used. The active fraud detection implementation now lives in the
`analytics` app (see `analytics/utils.py`). If you deleted `anti_fraud/` locally, it is
safe — the project uses `analytics` for all fraud/flagging functionality.

Quick start (macOS, python venv)

1. Create and activate the virtualenv (already included as `myenv` here):

```bash
python -m venv myenv
source myenv/bin/activate
pip install -r requirements.txt
```

2. Run migrations and create a superuser:

```bash
python manage.py migrate
python manage.py createsuperuser
```

3. Run the test suite:

```bash
python manage.py test
```

4. Run the dev server:

```bash
python manage.py runserver
```

Notes for beginners

- Look at `transactions/views.py` to understand money operations. Important
  concepts: `serializer.is_valid(raise_exception=True)`, `transaction.atomic()`,
  and `select_for_update()`.
- `analytics/utils.py` contains a simple fraud detector you can extend.
- We prefer small, readable functions rather than clever one-liners here so the
  code is easier to follow.

If you'd like, I can make the code even more beginner-friendly by:
- Adding inline `# WHY` comments where complex database or concurrency choices are used.
- Replacing small helper functions with explicit logic so the steps are easier to trace.
- Writing a short developer guide that explains how money moves through the system.

Which of these would you like next?

EMI endpoints (quick usage)

After an admin approves a loan the system credits the borrower's wallet and generates EMIs.

- List unpaid EMIs (authenticated):
  GET /loans/emis/ -> returns unpaid EMIs for current user

- Pay an EMI (authenticated):
  POST /loans/emis/{emi_id}/pay/ -> pays the EMI from the user's wallet

Troubleshooting (common issues)

- Tests failing: run `python manage.py test -v2` to see full trace. If a test fails after changes, run `python manage.py migrate` and re-run tests.
- Pylance/type warnings about `validated_data` or model attributes: ensure serializers call `is_valid(raise_exception=True)` before using `validated_data`. These warnings are static checks — runtime behavior is correct if tests pass.
- OpenAPI/schema issues: drf-spectacular may show duplicate inline serializer names if multiple inline serializers are declared separately; reusing central serializer definitions avoids that.# Banking_Api_Project
