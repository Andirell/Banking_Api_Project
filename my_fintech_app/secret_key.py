import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key


def resolve_secret_key(env_value, debug, key_file):
    # The secret key also signs the JWT tokens, so it must never be a value
    # written in the code (anyone reading GitHub could then make tokens).

    # 1. Use SECRET_KEY from the environment if it is set
    if env_value:
        return env_value

    # 2. In production it must be set, so stop here
    if not debug:
        raise ImproperlyConfigured("SECRET_KEY must be set when DEBUG is False.")

    # 3. Locally: reuse the key saved in key_file, or make a new random one
    key_file = Path(key_file)
    if key_file.exists():
        saved_key = key_file.read_text().strip()
        if saved_key:
            return saved_key

    key = get_random_secret_key()
    key_file.write_text(key)
    os.chmod(key_file, 0o600)  # only my user can read it
    return key
