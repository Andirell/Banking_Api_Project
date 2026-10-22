## Banking API Application ##

> **New here or testing the latest changes?** See [TESTING.md](TESTING.md) for what's new (2026-10-14), how to start the app locally, and a step-by-step walkthrough.
> **Changing the code?** Read [DEVELOPMENT.md](DEVELOPMENT.md) first. It explains how the apps fit together and the security rules to follow.
Overview

The Banking API is a backend service for a Digital Banking System built using Django and Django REST Framework (DRF). This API allows users to interact with the system by creating accounts, managing wallets, making transactions, applying for loans, and more.

## Key Features

User Authentication: Support for login, registration, and KYC (Know Your Customer) verification.
Wallet Management: Allows users to create wallets, deposit funds, withdraw funds, and transfer money.
Transaction Management: Users can perform peer-to-peer transfers and track their transaction history.
Loan Management: Users can apply for loans and check the status of their applications.
Admin Management: Admins can approve loans, block users, and monitor fraud activity.

## Features

User Features

Registration and Authentication: Users can create accounts and login using JWT tokens.
KYC Submission: Users can upload identity documents for verification.
Wallet Management: Create, update, and manage wallet balances.
Transactions: Transfer funds, deposit, and withdraw.
Loan Application: Apply for loans and track loan status.

Admin Features

Loan Approval: Admins can approve or reject loan applications.
Fraud Monitoring: Admins can check for suspicious activities and flag transactions.
User Management: Admins can block or unblock users.

Tech Stack

Backend: Django + Django REST Framework (DRF)
Database: PostgreSQL (managed by Render)
Authentication: JWT (JSON Web Token) + Django OTP for two-factor authentication
Payments: Stripe / Razorpay (for payment integrations)
Analytics: Pandas (for fraud detection)
Hosting: Render (for deployment)
Security: Django Security Middleware + whitenoise for static file handling

API Endpoints

Authentication & User
POST /users/signup/ - Register a new user.
POST /users/signin/ - User login (returns JWT token).
POST /users/kyc/submit/ - Submit KYC documents for verification.
POST /users/verify-signin-otp/ - Verify the emailed sign-in code and receive JWT tokens.

Wallet
POST /wallets/create/ - Create a new wallet for the user.
GET /wallets/details/ - Retrieve the user's wallet balance.
PUT /wallets/update/ - Update wallet details.

Transactions
POST /transactions/send/ - Transfer money to another user.
POST /transactions/withdraw/ - Withdraw money from the user's wallet.
POST /transactions/deposit/ - Deposit money into the user's wallet.
GET /transactions/history/ - Retrieve transaction history for the logged-in user.
GET /transactions/{id}/ - Retrieve details of a specific transaction.

Loan Management
POST /loans/apply/ - Apply for a loan.
GET /loans/status/{id}/ - Check the status of a loan application.
POST /admin/loans/approve/ - Admin approve loan application.

Admin
GET /admin/dashboard/ - View admin dashboard with key statistics.
POST /admin/block-user/ - Block a user.
POST /admin/unblock-user/ - Unblock a user.

Setup and Installation

Follow these steps to get your project up and running locally.

Prerequisites

Make sure you have the following installed:

Python 3.8 or higher
pip (Python package installer)
PostgreSQL (for database)
Git (for cloning the repository)

Clone the Repository
git clone https://github.com/Andirell/Banking_Api_Project/tree/main/users
cd your-repository

Create a Virtual Environment

It's recommended to use a virtual environment to manage dependencies.
python3 -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`

Install Dependencies

Install the required dependencies using pip:
pip install -r requirements.txt

Environment variables

Settings are read from the environment, or from a local `.env` file (never commit it). Everything is optional locally; production (`RENDER` set) needs at least `SECRET_KEY`.

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | generated into `.dev_secret_key` when DEBUG | Signs sessions and JWTs. **Required in production.** |
| `DEBUG` | on locally, off when `RENDER` is set | Never on in production. |
| `DATABASE_URL` | SQLite `db.sqlite3` | Postgres connection string, e.g. `postgres://user:pass@host:5432/db`. |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | Render hostname added automatically | Extra hosts and origins, comma-separated. |
| `EMAIL_BACKEND` | console (prints emails) | `anymail.backends.brevo.EmailBackend` on Render, or SMTP locally. |
| `ANYMAIL_BREVO_API_KEY` | — | Brevo API key when using the Brevo backend (any `ANYMAIL_*` variable is passed to django-anymail). |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | — / 587 / on | SMTP settings (local only; Render's free plan blocks SMTP). |
| `EMAIL_TIMEOUT` | `10` | Seconds before giving up on the mail server. |
| `DEFAULT_FROM_EMAIL` | `EMAIL_HOST_USER` | Sender of all emails (must be a verified sender in Brevo). |
| `FRONTEND_URL` | empty | Customer web app, e.g. `https://app.example.com`. Emails link to it; with no value they have no button. |
| `API_DOCS_PUBLIC` | same as DEBUG | Serve Swagger (`/api/docs/`) and the schema. Off in production unless set to `true`. |
| `UNVERIFIED_TRANSFER_LIMIT` | `5000.00` | Largest single transfer before KYC is verified. |
| `NUM_PROXIES` | `3` | Proxies that append to `X-Forwarded-For` (Render: client, Cloudflare, load balancer = 3). Used to find the real client IP for rate limits; set `0` when nothing sits in front of the app. |

Setup the Database

Without `DATABASE_URL` the app uses SQLite. For Postgres, set `DATABASE_URL`.

Run database migrations:
python manage.py migrate

Start the Development Server
python manage.py runserver

Testing the API

You can test the endpoints using tools like Postman or Swagger.

Swagger:
After running the Django server, visit http://127.0.0.1:8000/api/docs/ to see the Swagger UI, where you can interact with the API directly. On production it is only available when `API_DOCS_PUBLIC=true`.
Postman:
Open Postman and create requests based on the above API endpoint specifications.
Make sure to include the Authorization header with the JWT token for endpoints that require authentication.