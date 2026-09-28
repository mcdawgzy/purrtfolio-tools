"""Compatibility entry point: render.yaml / CI run `uvicorn src.api:app`. The app lives in src/main.py."""
from .main import app  # noqa: F401
