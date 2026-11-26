"""Entrypoint shim so `uvicorn app.main:app` resolves to `backend.main:app`."""

from backend.main import app

__all__ = ["app"]
