import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key


def resolve_secret_key(env_value, debug, key_file):
    """Return the signing key for this instance.

    The key also signs JWTs, so it must never be a value that exists in the
    source code. Production requires SECRET_KEY; local debug runs get a random
    key generated once and persisted to a gitignored file.
    """
    if env_value:
        return env_value
    if not debug:
        raise ImproperlyConfigured("SECRET_KEY must be set when DEBUG is False.")

    key_file = Path(key_file)
    if key_file.exists():
        existing = key_file.read_text().strip()
        if existing:
            return existing

    key = get_random_secret_key()
    key_file.write_text(key)
    os.chmod(key_file, 0o600)
    return key
