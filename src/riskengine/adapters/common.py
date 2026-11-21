"""Bounded HTTP transport and immutable raw-evidence storage."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import getproxies, proxy_bypass

import httpx


ADAPTER_VERSION = "1.0.0"
SENSITIVE = re.compile(r"(?:token|secret|password|authorization|api[_-]?key|signature|x-amz-|credential)", re.I)


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False, default=str).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class SourceError(Exception):
    def __init__(self, code, message, *, http_status=None):
        self.code, self.http_status = code, http_status
        super().__init__(message)


def safe_url(url):
    p = urlsplit(str(url))
    host = p.hostname or ""
    if p.port:
        host += f":{p.port}"
    q = [(k, "[REDACTED]" if SENSITIVE.search(k) else v) for k, v in parse_qsl(p.query, keep_blank_values=True)]
    return urlunsplit((p.scheme, host, p.path, urlencode(q), ""))


def public_url(url, *, resolve_dns=True):
    """Reject credentialled URLs, local/private destinations and unsupported schemes."""
    p = urlsplit(str(url))
    if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password:
        raise SourceError("INVALID_ENDPOINT", "Expected a public HTTP(S) endpoint without URL credentials")
    host = p.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain", "metadata.google.internal"} or host.endswith((".local", ".internal", ".localhost")):
        raise SourceError("PRIVATE_ENDPOINT", "Local and private network endpoints are not ingestion sources")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        if not resolve_dns:
            return
        try:
            addresses = [ipaddress.ip_address(row[4][0]) for row in socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)]
        except OSError as exc:
            raise SourceError("DNS_FAILED", f"Could not resolve source host {host}") from exc
    else:
        raise SourceError("LITERAL_IP_ENDPOINT", "Source endpoints require a registered public hostname, not a literal IP")
    if not addresses or any(not a.is_global for a in addresses):
        raise SourceError("PRIVATE_ENDPOINT", "Source host resolves to a non-public address")


def atomic_write(path: Path, body: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise SourceError("HASH_COLLISION", "Existing immutable payload differs from its content hash")
        return
    fd, name = tempfile.mkstemp(prefix=".capture-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Transport:
    """All requests originate from a registry contract. Redirects are revalidated.

    Byte budget applies to all response bodies in one collection, after HTTP
    decompression. Secrets are read from environment variables, never persisted.
    """
    def __init__(self, source, output_dir, max_bytes, *, client=None, sleep=time.sleep):
        self.source = source
        self.output_dir = Path(output_dir)
        self.max_bytes = int(max_bytes)
        self.consumed = 0
        self.raw_files = []
        self.requests = []
        self.resolution_events = []
        self.proxy_override = None
        self.active_proxy = None
        self.sleep = sleep
        self.owns_client = client is None
        self.headers = {"User-Agent": "PropertyRiskEngine/1.0", "Accept": "application/json"}
        self.auth = None
        self.secrets = []
        # An explicitly supplied local asset is an offline import. No remote
        # credential is needed, even when the corresponding live feed needs one.
        auth = {} if source.get("parameters", {}).get("local_path") else (source.get("auth_env") or source.get("parameters", {}).get("auth_env") or {})
        headers = auth.get("headers", {})
        for header, env_name in headers.items():
            value = os.environ.get(env_name)
            if not value:
                raise SourceError("CREDENTIALS_REQUIRED", f"Missing environment variable {env_name}")
            self.headers[header] = value
            self.secrets.append(value)
        basic = auth.get("basic")
        if basic:
            user, password = os.environ.get(basic["username"]), os.environ.get(basic["password"])
            if not user or not password:
                raise SourceError("CREDENTIALS_REQUIRED", "Configured HTTP Basic credentials are missing")
            self.auth = httpx.BasicAuth(user, password)
            self.secrets.extend([user, password])
        self.query_auth = {}
        for key, env_name in auth.get("query", {}).items():
            value = os.environ.get(env_name)
            if not value:
                raise SourceError("CREDENTIALS_REQUIRED", f"Missing environment variable {env_name}")
            self.query_auth[key] = value
            self.secrets.append(value)
        self.base_host = urlsplit(str(source.get("endpoint", ""))).hostname
        self.client = client

    def _validate_url(self, url):
        """Allow remote DNS only through a configured HTTPS CONNECT/SOCKS proxy.

        The fallback is restricted to registered HTTPS hostnames. A failed local
        lookup in an environment that intentionally resolves through a proxy is
        not evidence that the approved public source is unavailable. A local
        private-address answer is still rejected; it never triggers fallback.
        """
        parts = urlsplit(url)
        registered = {self.base_host, *self.source.get("allowed_hosts", [])}
        if parts.hostname not in registered:
            raise SourceError("UNREGISTERED_HOST", "Request or redirect host is absent from the trusted source contract")
        try:
            public_url(url)
        except SourceError as exc:
            proxies = getproxies()
            proxy = next((proxies.get(key) for key in ("https", "all")
                          if urlsplit(proxies.get(key, "")).scheme.lower() in {"http", "https", "socks5h"}), None)
            remote_dns = proxy is not None
            if exc.code != "DNS_FAILED" or parts.scheme != "https" or not remote_dns or proxy_bypass(parts.hostname):
                raise
            public_url(url, resolve_dns=False)
            self.proxy_override = proxy
            mode = "REGISTERED_HTTPS_SOCKS_REMOTE_DNS" if urlsplit(proxy).scheme.lower() == "socks5h" else "REGISTERED_HTTPS_CONNECT_PROXY_DNS"
            event = {"host": parts.hostname, "mode": mode}
            if event not in self.resolution_events:
                self.resolution_events.append(event)

    def _ensure_client(self):
        if self.owns_client and (self.client is None or self.active_proxy != self.proxy_override):
            if self.client is not None:
                self.client.close()
            try:
                # An explicitly configured remote-DNS route is selected only after
                # the registered-host remote-DNS check. No proxy is disabled.
                self.client = httpx.Client(timeout=httpx.Timeout(30.0), follow_redirects=False,
                                           proxy=self.proxy_override)
                self.active_proxy = self.proxy_override
            except ImportError as exc:
                raise SourceError("DEPENDENCY_MISSING", "HTTP proxy support is unavailable; install the declared httpx[socks] dependency") from exc

    def close(self):
        if self.owns_client and self.client is not None:
            self.client.close()

    def redact(self, value):
        text = str(value)
        for secret in self.secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text

    def _store(self, body, kind, url, response=None, suffix="bin"):
        h = hashlib.sha256(body).hexdigest()
        suffix = suffix if suffix in {"json", "csv", "xlsx", "zip", "xml", "html", "txt", "pdf", "bin"} else "bin"
        rel = Path("raw") / h[:2] / f"{h}.{suffix}"
        atomic_write(self.output_dir / rel, body)
        item = {"sha256": h, "bytes": len(body), "path": str(self.output_dir / rel),
                "relative_path": str(rel), "kind": kind, "url": self.redact(safe_url(url))}
        if response is not None:
            item.update(http_status=response.status_code, content_type=response.headers.get("content-type"),
                        etag=response.headers.get("etag"), last_modified=response.headers.get("last-modified"))
        self.raw_files.append(item)
        return body

    def local(self, path, *, kind="local_file", suffix="bin"):
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise SourceError("LOCAL_FILE_MISSING", "Configured local source file does not exist")
        remaining = self.max_bytes-self.consumed
        if p.stat().st_size > remaining:
            raise SourceError("BYTE_LIMIT", "Local file exceeds collection byte budget")
        body = p.read_bytes()
        self.consumed += len(body)
        # The path is a private local locator, never an HTTP endpoint.
        return self._store(body, kind, "local://selected-input/"+p.name, suffix=suffix)

    def fetch(self, url, *, params=None, kind="response", suffix="json", accept=None):
        self._validate_url(url)
        self._ensure_client()
        params = {**dict(parse_qsl(urlsplit(url).query, keep_blank_values=True)), **dict(params or {}), **self.query_auth}
        headers = {**self.headers}
        if accept:
            headers["Accept"] = accept
        auth = self.auth
        target = str(httpx.URL(url, params=params))
        retries = min(3, max(0, int(self.source.get("parameters", {}).get("retries", 2))))
        for redirect in range(6):
            self._validate_url(target)
            self._ensure_client()
            redirected = None
            for attempt in range(retries+1):
                if self.consumed >= self.max_bytes:
                    raise SourceError("BYTE_LIMIT", "Collection byte budget has been reached")
                try:
                    with self.client.stream("GET", target, headers=headers, auth=auth, follow_redirects=False) as response:
                        self.requests.append({"url": self.redact(safe_url(target)), "status": response.status_code, "attempt": attempt+1})
                        if response.status_code in (301, 302, 303, 307, 308):
                            if not response.headers.get("location"):
                                raise SourceError("INVALID_REDIRECT", "Redirect lacks a Location header")
                            redirected = urljoin(target, response.headers["location"])
                            if urlsplit(target).scheme == "https" and urlsplit(redirected).scheme != "https":
                                raise SourceError("INSECURE_REDIRECT", "Source attempted to downgrade an HTTPS request")
                            self._validate_url(redirected)
                            if urlsplit(redirected).hostname != urlsplit(target).hostname:
                                # Never forward API credentials across a redirect boundary.
                                if any(secret and secret in redirected for secret in self.secrets):
                                    raise SourceError("CREDENTIAL_REDIRECT_BLOCKED", "Cross-host redirect would disclose a configured credential")
                                headers = {"User-Agent": "PropertyRiskEngine/1.0", "Accept": accept or "application/json"}
                                auth = None
                            break
                        if response.status_code in (401, 403):
                            raise SourceError("ACCESS_DENIED", "Source requires authorised access or denied this request", http_status=response.status_code)
                        if response.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                            retry = response.headers.get("retry-after", "")
                            delay = min(2**attempt, 4)
                            if re.match(r"^\d+(\.\d+)?$", retry):
                                delay = float(retry)
                            elif retry:
                                try:
                                    retry_at = parsedate_to_datetime(retry)
                                    if retry_at.tzinfo is None:
                                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                                    delay = max(0, (retry_at - datetime.now(timezone.utc)).total_seconds())
                                except (ValueError, TypeError, OverflowError):
                                    pass
                            if delay > 10:
                                raise SourceError("RETRY_DEFERRED", "Source requested a later retry; collection stopped without retrying early", http_status=response.status_code)
                            self.sleep(delay)
                            continue
                        if response.status_code >= 400:
                            raise SourceError("HTTP_ERROR", f"Source returned HTTP {response.status_code}", http_status=response.status_code)
                        length = response.headers.get("content-length", "")
                        if length.isdigit() and int(length) > self.max_bytes-self.consumed:
                            raise SourceError("BYTE_LIMIT", "Declared response size exceeds the remaining collection byte budget")
                        chunks = []
                        for chunk in response.iter_bytes(chunk_size=65_536):
                            self.consumed += len(chunk)
                            if self.consumed > self.max_bytes:
                                raise SourceError("BYTE_LIMIT", "Response exceeded collection byte budget; partial bytes were not accepted")
                            chunks.append(chunk)
                        body = b"".join(chunks)
                        return self._store(body, kind, target, response, suffix)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt >= retries:
                        raise SourceError("NETWORK_ERROR", "Source transport failed after bounded retries") from exc
                    self.sleep(min(2**attempt, 4))
            if redirected:
                target = redirected
                continue
        raise SourceError("REDIRECT_LIMIT", "Source exceeded the redirect limit")

    def json(self, url, *, params=None, kind="response"):
        body = self.fetch(url, params=params, kind=kind, suffix="json")
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceError("INVALID_JSON", "Source did not return valid JSON") from exc
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            message = err.get("message", "Source service error") if isinstance(err, dict) else data.get("message", "Source service error")
            raise SourceError("SERVICE_ERROR", self.redact(message))
        return data

