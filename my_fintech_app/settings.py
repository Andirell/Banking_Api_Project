"""Settings for the banking API.

Values that change between my laptop and Render come from environment
variables (or a local .env file). The full list is in README.md.
"""

import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

from my_fintech_app.secret_key import resolve_secret_key

# Read the .env file if there is one
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    # Turns "true", "1", "yes" or "on" into True
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def env_list(name):
    # Turns "a.com, b.com" into ["a.com", "b.com"]
    items = []
    for item in os.getenv(name, "").split(","):
        if item.strip():
            items.append(item.strip())
    return items


# ---------------------------------------------------------------------------
# Debug, secret key and allowed hosts
# ---------------------------------------------------------------------------

# Debug is on locally and off on Render (Render sets the RENDER variable)
DEBUG = env_bool("DEBUG", default=not env_bool("RENDER"))

# The secret key also signs our JWT tokens, so there is no default value in
# the code. On Render it must be set. Locally a random one is made and saved
# in .dev_secret_key (which is in .gitignore).
SECRET_KEY = resolve_secret_key(os.getenv("SECRET_KEY"), DEBUG, BASE_DIR / ".dev_secret_key")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Render tells us our own address
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

# In production everything must use HTTPS. Render handles the certificate
# and tells us the original scheme in the X-Forwarded-Proto header.
# The password reset step keeps data in the session, so its cookie must
# never be sent over plain HTTP.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [r"^health/$"]  # Render's health check uses plain HTTP
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # packages
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',

    # my apps
    'users',
    'transactions',
    'wallets',
    'loans',
    'analytics',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'my_fintech_app.urls'
WSGI_APPLICATION = 'my_fintech_app.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Users and login
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = "users.User"

# Our login backend locks an account for 15 minutes after 5 wrong passwords
# (this covers the API sign-in and the Django admin login)
AUTHENTICATION_BACKENDS = ["users.backends.LockoutModelBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# The biggest single transfer allowed before a user's KYC is verified.
# Loans and withdrawals always need verified KYC.
UNVERIFIED_TRANSFER_LIMIT = Decimal(os.getenv("UNVERIFIED_TRANSFER_LIMIT", "5000.00"))


# ---------------------------------------------------------------------------
# Django REST Framework and JWT
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    # Every endpoint needs login unless the view says otherwise
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'otp': '10/minute',      # sign-in and OTP endpoints, per IP
        'signup': '5/hour',      # new accounts, per IP
        'transfer': '30/hour',   # transfers, per user
    },
    # To limit by IP we read the X-Forwarded-For header. On Render each
    # request passes through 3 proxies, and the header ends like this:
    #   ...anything the client made up..., real client IP, Cloudflare, Render
    # So the real client IP is the 3rd one from the end. (Checked on 2026-10-15.)
    'NUM_PROXIES': int(os.getenv('NUM_PROXIES', 3)),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SIMPLE_JWT = {
    # Access tokens are short so a stolen one is only useful for a little while.
    # Apps get a new one from POST /users/token/refresh/.
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    # Each refresh token works once: refreshing gives a new one and blocks the old one
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'ALGORITHM': 'HS256',
    # Tokens stop working when the user changes their password
    'CHECK_REVOKE_TOKEN': True,
}

# Swagger docs at /api/docs/. On by default locally, off in production.
API_DOCS_PUBLIC = env_bool("API_DOCS_PUBLIC", default=DEBUG)

SPECTACULAR_SETTINGS = {
    'TITLE': "Fintech Application API",
    'DESCRIPTION': "A list of all my endpoints for my fintech application.",
    'VERSION': '1.0.0',
}


# ---------------------------------------------------------------------------
# Database and cache
# ---------------------------------------------------------------------------

# SQLite on my laptop, PostgreSQL on Render (set DATABASE_URL)
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.config(default=DATABASE_URL, conn_max_age=600, conn_health_checks=True)
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# The rate limits store their counters in the cache. On Render several
# worker processes run at once, and a normal in-memory cache would give each
# worker its own counters (so the limits would be multiplied). The database
# cache is shared by all of them. Its table is made by "createcachetable" in build.sh.
if not DEBUG:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "django_cache",
        }
    }


# ---------------------------------------------------------------------------
# Time and language
# ---------------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# KYC documents go here. This folder is never served by a URL; files are
# only downloaded through a view that checks who is asking.
PRIVATE_MEDIA_ROOT = BASE_DIR / 'private_media'


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD") or os.getenv("APP_PASSWORD")
# Without a timeout, a mail server we can't reach would make requests hang
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", 10))

# Render's free plan blocks normal email (SMTP), so in production we send
# through an email API with django-anymail. Set EMAIL_BACKEND to something like
# "anymail.backends.brevo.EmailBackend" and the key as ANYMAIL_BREVO_API_KEY=...
# Every ANYMAIL_* variable is copied into this dictionary.
ANYMAIL = {}
for name, value in os.environ.items():
    if name.startswith("ANYMAIL_"):
        ANYMAIL[name[len("ANYMAIL_"):]] = value

DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "webmaster@localhost")

# The customer website. Links in emails point here (no links if it's empty).
FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")
