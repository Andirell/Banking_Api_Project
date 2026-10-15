from pathlib import Path
from dotenv import load_dotenv
import os
from datetime import timedelta
from django.core.exceptions import ImproperlyConfigured
from my_fintech_app.secret_key import resolve_secret_key

try:
    import dj_database_url
except ImportError:
    dj_database_url = None

# Load environment variables from the .env file
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool("DEBUG", default=not env_bool("RENDER"))

# SECURITY WARNING: keep the secret key used in production secret!
# It also signs JWTs, so there is deliberately no hard-coded fallback.
SECRET_KEY = resolve_secret_key(os.getenv("SECRET_KEY"), DEBUG, BASE_DIR / ".dev_secret_key")

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

# HTTPS-only in production. Render terminates TLS at its proxy and passes the
# original scheme in X-Forwarded-Proto. The password-reset grant lives in the
# session, so its cookie must never travel over plain HTTP.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [r"^health/$"]  # Render's internal health check uses plain HTTP
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Package apps
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',

    # Your apps
    'users',
    'transactions',
    'wallets',
    'loans',
    'analytics',
]

CORS_ALLOWED_ORIGINS = []  # Add allowed origins for production
CORS_ALLOW_ALL_ORIGINS = True  # Set to False in production and use CORS_ALLOWED_ORIGINS

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

AUTH_USER_MODEL = "users.User"

ROOT_URLCONF = 'my_fintech_app.urls'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication'  # It decodes your token
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated'  # Makes all endpoints or URLs protected
    ],
    'DEFAULT_THROTTLE_RATES': {
        'otp': '10/minute',  # Per-IP limit on anonymous OTP endpoints (see users.throttles)
    },
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema'
}

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

WSGI_APPLICATION = 'my_fintech_app.wsgi.application'

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1),  # Set expiration for access token
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),  # Set expiration for refresh token
    'SIGNING_KEY': SECRET_KEY,  # Your Django key to give the token a unique signature or to sign the token
    'AUTH_HEADER_TYPES': ('Bearer',),  # The type of authorization header. It is the label of the token
    'ALGORITHM': 'HS256',  # The algorithm used to sign the token. The formula on how the token is made
    'CHECK_REVOKE_TOKEN': True,  # Tokens carry a password hash claim, so a password change revokes them
}

SPECTACULAR_SETTINGS = {
    'TITLE': "Fintech Application API",
    'DESCRIPTION': "A list of all my endpoints for my fintech application.",
    'VERSION': '1.0.0'
}

# Database Configuration (SQLite in Development, PostgreSQL on Render)
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    if dj_database_url is None:
        raise ImproperlyConfigured("dj-database-url is required when DATABASE_URL is set.")

    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization settings
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Media files (Uploaded by users)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Private uploads (KYC documents). Never served by URL; read through an authorising view.
PRIVATE_MEDIA_ROOT = BASE_DIR / 'private_media'

# SMTP Configuration for sending emails
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD") or os.getenv("APP_PASSWORD")
# Without a timeout an unreachable mail server (e.g. Render free blocks SMTP) hangs the request.
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", 10))

# HTTP email APIs via django-anymail, for hosts that block SMTP (Render free).
# Set EMAIL_BACKEND to e.g. "anymail.backends.brevo.EmailBackend" and pass the
# provider settings as ANYMAIL_* env vars, e.g. ANYMAIL_BREVO_API_KEY=...
ANYMAIL = {
    name[len("ANYMAIL_"):]: value
    for name, value in os.environ.items()
    if name.startswith("ANYMAIL_")
}
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "webmaster@localhost")
