"""Deterministic property evidence and buyer-case assessment."""
from pathlib import Path
import os

__version__ = "0.1.0"


def _load_dotenv() -> None:
    """Load local .env values without overriding explicitly set environment variables."""
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

