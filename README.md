## Banking API Application ##
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
POST /users/verify-otp/ - Verify OTP during login.

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

Setup the Database

Configure your PostgreSQL database in the .env file.
DB_NAME=your_database_name
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_HOST=localhost
DB_PORT=5432

Run database migrations:
python manage.py migrate

Start the Development Server
python manage.py runserver

Testing the API

You can test the endpoints using tools like Postman or Swagger.

Swagger:
After running the Django server, visit http://127.0.0.1:8000/api/docs/ to see the Swagger UI, where you can interact with the API directly.
Postman:
Open Postman and create requests based on the above API endpoint specifications.
Make sure to include the Authorization header with the JWT token for endpoints that require authentication.