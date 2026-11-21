"""Browser access for a local single-user workspace or the dedicated sample preview."""
from pathlib import Path
import secrets
from tempfile import NamedTemporaryFile
from time import monotonic
import webbrowser

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from .paths import project_root


class LocalDashboard:
    def __init__(self, mode, host, port, tenant, directory):
        if host != "127.0.0.1" or not 1 <= port <= 65535:
            raise ValueError("The desktop dashboard requires a fixed port on 127.0.0.1")
        if mode not in {"desktop", "preview"}:
            raise ValueError("Unknown dashboard mode")
        if mode == "preview" and (
            directory != (project_root() / "runtime" / "buyer-preview").resolve()
            or tenant != "demo"
        ):
            raise ValueError("The sample preview requires runtime/buyer-preview and the demo tenant")
        self.mode = mode
        self.directory = directory
        self.tenant = tenant
        self.authority = host if port == 80 else f"{host}:{port}"
        self.origin = f"http://{self.authority}"
        self.cookie_name = f"risk_desktop_{port}"
        self.session = secrets.token_urlsafe(32)
        self.launch_code = None
        self.launch_expiry = 0
        self.launch_path = None

    def open_browser(self):
        self.launch_code = secrets.token_urlsafe(32)
        self.launch_expiry = monotonic() + 300
        with NamedTemporaryFile(mode="w", encoding="utf-8", prefix="desktop-", suffix=".html",
                                dir=self.directory, delete=False) as launch:
            self.launch_path = Path(launch.name)
            launch.write(f"""<!doctype html><meta charset="utf-8"><title>Open Property Risk</title>
<form method="post" action="{self.origin}/desktop/open">
<input type="hidden" name="code" value="{self.launch_code}"><button>Open Property Risk</button></form>
<script>document.forms[0].submit()</script>""")
        print(f"Opening your workspace. If the browser does not open, open {self.launch_path}", flush=True)
        webbrowser.open(self.launch_path.as_uri())

    def close(self):
        self.launch_code = None
        if self.launch_path:
            self.launch_path.unlink(missing_ok=True)
            self.launch_path = None

    def local_request(self, request):
        return (request.client is not None and request.client.host == "127.0.0.1"
                and request.headers.get("host") == self.authority
                and request.url.scheme == "http"
                and not any(h.lower().startswith(("forwarded", "x-forwarded-")) for h in request.headers))

    async def open_session(self, request: Request):
        if (not self.local_request(request) or request.headers.get("origin") != "null"
                or request.headers.get("content-type") != "application/x-www-form-urlencoded"):
            raise HTTPException(403, "Open this workspace from the local launcher")
        body = await request.body()
        if (not self.launch_code or monotonic() >= self.launch_expiry
                or not secrets.compare_digest(body, b"code=" + self.launch_code.encode())):
            raise HTTPException(403, "This launch has expired. Restart the local launcher.")
        self.close()
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(self.cookie_name, self.session, httponly=True, samesite="strict", path="/v1/")
        return response

    def browser_tenant(self, request):
        if (not self.local_request(request) or request.headers.get("sec-fetch-site") != "same-origin"
                or request.headers.get("x-risk-dashboard") != "1"):
            return None
        origin = request.headers.get("origin")
        if origin != self.origin and (origin is not None or request.method not in {"GET", "HEAD"}):
            return None
        if self.mode == "desktop":
            supplied = request.cookies.get(self.cookie_name, "").encode()
            if not secrets.compare_digest(supplied, self.session.encode()):
                return None
        return self.tenant
