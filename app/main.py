"""Entrypoint Vercel looks for (app/main.py). The app itself is defined in app/api.py."""

from app.api import app  # noqa: F401
