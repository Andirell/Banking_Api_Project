#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
python manage.py collectstatic --no-input
python manage.py migrate
python manage.py createcachetable  # shared rate-limit counters (CACHES in settings.py)
