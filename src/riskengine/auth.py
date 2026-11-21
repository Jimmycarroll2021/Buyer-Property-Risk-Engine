"""Local API bearer authentication. Keys never enter report or audit payloads."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import secrets

from fastapi import HTTPException, Request
from .storage import validate_id


def validate_api_keys(keys):
    if not isinstance(keys, dict) or any(not isinstance(k, str) or len(k) < 24 or not isinstance(v, str) or not v for k, v in keys.items()):
        raise ValueError("API keys must map secrets of at least 24 characters to tenant identifiers")
    for tenant in keys.values():
        validate_id(tenant, "tenant ID")
        if tenant == "_public":
            raise ValueError("Reserved tenant identifier")
    return keys


def load_api_keys(data_dir: Path) -> dict[str, str]:
    raw = os.environ.get("RISK_API_KEYS_JSON")
    if raw:
        keys = json.loads(raw)
    elif (data_dir / "api_keys.json").is_file():
        keys = json.loads((data_dir / "api_keys.json").read_text())
    else:
        keys = {}
    return validate_api_keys(keys)


class BearerAuth:
    def __init__(self, keys: dict[str, str], dashboard=None):
        validate_api_keys(keys)
        if dashboard and set(keys.values()) != {dashboard.tenant}:
            raise ValueError("Local dashboard access requires exactly the selected tenant in the key mapping")
        self.dashboard = dashboard
        self._keys = [(hashlib.sha256(key.encode()).digest(), tenant) for key, tenant in keys.items()]

    async def __call__(self, request: Request) -> str:
        if self.dashboard and "authorization" not in request.headers:
            tenant = self.dashboard.browser_tenant(request)
            if tenant:
                return tenant
        header = request.headers.get("authorization", "")
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "bearer" or not value or len(value) > 4096:
            raise HTTPException(401, "A valid bearer API key is required", headers={"WWW-Authenticate": "Bearer"})
        digest = hashlib.sha256(value.encode()).digest()
        found = None
        for expected, tenant in self._keys:
            if secrets.compare_digest(digest, expected):
                found = tenant
        if found is None:
            raise HTTPException(401, "A valid bearer API key is required", headers={"WWW-Authenticate": "Bearer"})
        return found
