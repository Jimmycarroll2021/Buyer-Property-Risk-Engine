"""Authenticated local-first HTTP API. No runtime generative model is used."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .auth import BearerAuth, load_api_keys
from .preoffer_assessment import buyer_first
from .reporting import render_assessment
from .storage import Conflict, Forbidden, NotFound, Store, StoreError, SURVIVAL_AMOUNTS, SURVIVAL_MONTHS, utc_now


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app, maximum=8_000_000):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid Content-Length"}, 400)(scope, receive, send)
        if length > self.maximum:
            return await JSONResponse({"detail": "Request body exceeds 8 MB"}, 413)(scope, receive, send)
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.maximum:
                    raise BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except BodyTooLarge:
            await JSONResponse({"detail": "Request body exceeds 8 MB"}, 413)(scope, receive, send)


class CollectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=160)
    max_records: int = Field(default=1000, ge=1, le=100000)
    max_bytes: int = Field(default=20000000, ge=1024, le=100000000)
    bounds: dict[str, Any] | None = None


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    note: str = Field(min_length=1, max_length=5000)
    finding_id: str | None = None


class SurvivalPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assessment_id: str = Field(min_length=1, max_length=160)
    case_version: int = Field(ge=1, strict=True)
    changes: dict[str, Any]


class DocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(max_length=7000000)
    media_type: str = "text/plain"
    rights: dict[str, bool] = Field(default_factory=lambda: {"process": True, "display_raw": True, "display_derived": True, "retain_raw": True})


def safe_source_metadata(value):
    """Registry display never reveals nested credentials or URL credentials."""
    sensitive = {"credentials", "headers", "auth", "authorization", "secret", "api_key", "apikey", "password", "token", "access_token", "client_secret", "key", "signature", "sig"}
    if isinstance(value, dict):
        return {k: safe_source_metadata(v) for k, v in value.items() if k.lower() not in sensitive}
    if isinstance(value, list):
        return [safe_source_metadata(item) for item in value]
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        parts = urlsplit(value)
        hostname = parts.hostname or ""
        host = hostname + (f":{parts.port}" if parts.port else "")
        query = urlencode([(k, "[redacted]" if k.lower() in sensitive else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)])
        return urlunsplit((parts.scheme, host, parts.path, query, parts.fragment))
    return value


def document_metadata(document):
    return {k: v for k, v in document.items() if k != "raw_files"}


def create_app(data_dir=None, api_keys=None, *, dashboard=None) -> FastAPI:
    directory = Path(data_dir or os.environ.get("RISK_DATA_DIR", "runtime")).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    store = Store(directory / "riskengine.sqlite3")
    configured_keys = api_keys if api_keys is not None else load_api_keys(directory)
    if not isinstance(configured_keys, dict):
        raise ValueError("api_keys must be a secret-to-tenant mapping")
    if dashboard and dashboard.directory != directory:
        raise ValueError("The dashboard must use its configured data directory")
    auth = BearerAuth(configured_keys, dashboard)
    app = FastAPI(title="Property Risk Engine", version="1.0.0",
                  description="Deterministic evidence, buyer scenarios and explicit assessment gaps. Authenticate with a local bearer key.")
    app.add_middleware(BodyLimitMiddleware)
    app.state.store, app.state.data_dir = store, directory
    if dashboard and dashboard.mode == "desktop":
        app.add_api_route("/desktop/open", dashboard.open_session, methods=["POST"], include_in_schema=False)

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path == "/" or request.url.path.startswith(("/v1/", "/desktop/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(StoreError)
    async def store_error(_request, exc):
        code = 404 if isinstance(exc, NotFound) else 403 if isinstance(exc, Forbidden) else 409 if isinstance(exc, Conflict) else 422
        return JSONResponse({"detail": str(exc)}, status_code=code)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "property-risk-engine", "authentication_configured": bool(configured_keys), "backend": "sqlite"}

    from .weekend_routes import register_weekend
    register_weekend(app, store, auth, dashboard)

    @app.get("/v1/sources")
    def sources(tenant: str = Depends(auth)):
        from .ingestion import load_registry
        registered = load_registry()
        # Connector credential values must live in environment/secret storage.
        return {"sources": safe_source_metadata(registered)}

    @app.get("/v1/source-health")
    def source_health(tenant: str = Depends(auth)):
        return {"sources": store.get_source_health(tenant)}

    @app.post("/v1/cases", status_code=201)
    def save_case(body: dict = Body(...), expected_version: int | None = Query(default=None, ge=0), tenant: str = Depends(auth)):
        if "weekend_study" in body:
            try:
                original = store.get_case(tenant, body.get("case_id", ""))
            except NotFound:
                original = {}
            if body["weekend_study"] != original.get("weekend_study") or "weekend_study" not in original:
                raise StoreError("Edit price, cash and property assumptions in the weekend worksheet")
        if dashboard and dashboard.mode == "preview":
            options = body.get("preoffer") or {}
            if isinstance(options, dict) and (options.get("comparable_sales") or options.get("underwriting")):
                raise Forbidden("Save private sales and underwriting evidence in your personal workspace")
            scenario_inputs = isinstance(options, dict) and (
                options.get("finance") or (SURVIVAL_AMOUNTS | SURVIVAL_MONTHS).intersection(options))
            if (body.get("finance") or body.get("buyer_protection") or scenario_inputs) and not (
                    body.get("finance_is_illustrative") is True or body.get("demonstration") is True):
                raise Forbidden("Use illustrative finances in this sample workspace or open your personal workspace")
        return store.save_case(tenant, body, expected_version)

    @app.get("/v1/cases")
    def list_cases(tenant: str = Depends(auth)):
        return {"cases": store.list_cases(tenant)}

    @app.get("/v1/cases/{case_id}")
    def get_case(case_id: str, version: int | None = Query(default=None, ge=1), tenant: str = Depends(auth)):
        return store.get_case(tenant, case_id, version, for_display=True)

    @app.get("/v1/locations/search")
    def address_search(street: str = Query(min_length=3, max_length=120), suburb: str = Query(min_length=1, max_length=80),
                       tenant: str = Depends(auth)):
        import httpx
        from .preoffer_locations import lookup_addresses
        if store.restricted_decision_sources(tenant, ("act_addresses",)):
            raise Forbidden("The ACT address register is restricted for this workspace")
        try:
            return lookup_addresses(street, suburb)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (httpx.HTTPError, RuntimeError, KeyError) as exc:
            raise HTTPException(503, "The ACT address register is unavailable. Try again or enter known coordinates.") from exc

    @app.get("/v1/locations/examples")
    def retained_addresses(tenant: str = Depends(auth)):
        from .preoffer_locations import examples
        if store.restricted_decision_sources(tenant, ("act_addresses",)):
            raise Forbidden("The ACT address register is restricted for this workspace")
        return examples()

    @app.get("/v1/locations/kingston-example")
    def kingston_example(tenant: str = Depends(auth)):
        from .buyer_location import example_case
        return example_case()

    @app.get("/v1/cases/{case_id}/buyer-context")
    def get_buyer_context(case_id: str, version: int = Query(ge=1), assessment_id: str | None = None,
                          tenant: str = Depends(auth)):
        from .buyer_context import LOCAL_SOURCES, buyer_context
        case = store.get_case(tenant, case_id, version)
        assessment = None
        if assessment_id:
            entries = store.list_assessments(tenant, case_id)
            if not any(item["assessment_id"] == assessment_id and item["case_version"] == version for item in entries):
                raise HTTPException(409, "The assessment does not belong to this case version")
            assessment = store.get_assessment(tenant, assessment_id)
            if "decision_evidence" in assessment:
                return {**assessment["decision_evidence"], "assessment_id": assessment_id}
        restricted = store.restricted_decision_sources(tenant, LOCAL_SOURCES)
        return buyer_context(case, assessment, restricted_sources=restricted)

    @app.post("/v1/cases/{case_id}/observations", status_code=201)
    def add_observation(case_id: str, body: dict = Body(...), tenant: str = Depends(auth)):
        # Actual private receipt cannot be backdated by an HTTP input.
        body = {k: v for k, v in body.items() if k != "received_at"}
        record = store.add_observation(tenant, case_id, body, trusted_public=False, server_received_at=True)
        # Current source restrictions apply to writes as well as later reads.
        return next(item for item in store.list_observations(tenant, case_id, redact=True)
                    if item["observation_id"] == record["observation_id"] and item.get("owner_tenant_id") == tenant)

    @app.get("/v1/cases/{case_id}/observations")
    def list_observations(case_id: str, tenant: str = Depends(auth)):
        return {"observations": store.list_observations(tenant, case_id, redact=True)}

    @app.post("/v1/cases/{case_id}/assessments", status_code=201)
    def assess(case_id: str, body: dict | None = Body(default=None), expected_version: int | None = Query(default=None, ge=1),
               tenant: str = Depends(auth)):
        if body:
            raise HTTPException(422, "Assessment uses the stored case and configured required-check catalogue; request overrides are not accepted")
        from .pipeline import assess_case
        try:
            return buyer_first(assess_case(store, tenant, case_id, expected_version=expected_version))
        except StoreError:
            raise
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, f"Invalid assessment input: {exc}") from exc

    @app.get("/v1/cases/{case_id}/assessments")
    def list_assessments(case_id: str, tenant: str = Depends(auth)):
        return {"assessments": store.list_assessments(tenant, case_id)}

    @app.post("/v1/cases/{case_id}/survival-preview")
    def survival_preview(case_id: str, body: SurvivalPreviewRequest, tenant: str = Depends(auth)):
        from .preoffer_assessment import PREOFFER_VERSION, calculate_survival, case_with_home
        from .storage import _validate_preoffer

        allowed = {"lost_income_monthly", "loss_months", "extra_expense_monthly", "repair_cost", "repair_month",
                   "repair_overrun_pct", "rate_rise_bps"}
        if set(body.changes) - allowed:
            raise StoreError("Only the first-year stress assumptions can be adjusted here")
        _validate_preoffer({"preoffer": body.changes})
        case, _, saved = store.replay_inputs(tenant, body.assessment_id)
        if case["case_id"] != case_id or case["case_version"] != body.case_version:
            raise Conflict("Select the saved assessment for this case version")
        if saved.get("preoffer_version") != PREOFFER_VERSION:
            raise Conflict("Assess this case with the current household rules before changing its assumptions")
        if dashboard and dashboard.mode == "preview" and not saved["preoffer_brief"]["illustrative_finance"]:
            raise Forbidden("Adjust actual household figures in your personal workspace")
        case = case_with_home(case, saved["preoffer_capture"]["home"])
        try:
            return calculate_survival(case, saved, {**(case.get("preoffer") or {}), **body.changes})
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise StoreError(str(exc)) from exc

    @app.get("/v1/assessments/{assessment_id}")
    def get_assessment(assessment_id: str, tenant: str = Depends(auth)):
        return buyer_first(store.get_assessment(tenant, assessment_id))

    @app.get("/v1/assessments/{assessment_id}/report", response_class=HTMLResponse)
    def report(assessment_id: str, tenant: str = Depends(auth)):
        return render_assessment(store.get_assessment(tenant, assessment_id))

    @app.post("/v1/assessments/{assessment_id}/reviews", status_code=201)
    def review(assessment_id: str, body: ReviewRequest, tenant: str = Depends(auth)):
        return store.add_review(tenant, assessment_id, body.action, body.note, body.finding_id)

    @app.get("/v1/assessments/{assessment_id}/reviews")
    def reviews(assessment_id: str, tenant: str = Depends(auth)):
        return {"reviews": store.list_reviews(tenant, assessment_id)}

    @app.post("/v1/cases/{case_id}/collect")
    def collect(case_id: str, body: CollectRequest, tenant: str = Depends(auth)):
        store.get_case(tenant, case_id)
        from .pipeline import collect_case
        try:
            return collect_case(store=store, tenant_id=tenant, case_id=case_id, source_id=body.source_id,
                                output_dir=directory / "snapshots", max_records=body.max_records,
                                max_bytes=body.max_bytes, bounds=body.bounds)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/v1/jobs")
    def jobs(case_id: str | None = None, tenant: str = Depends(auth)):
        return {"jobs": store.list_jobs(tenant, case_id)}

    @app.get("/v1/jobs/{job_id}")
    def job(job_id: str, tenant: str = Depends(auth)):
        return store.get_job(tenant, job_id)

    @app.get("/v1/cases/{case_id}/audit")
    def audit(case_id: str, tenant: str = Depends(auth)):
        return {"events": store.audit_events(tenant, case_id)}

    @app.post("/v1/cases/{case_id}/documents", status_code=201)
    def upload_document(case_id: str, body: DocumentRequest, tenant: str = Depends(auth)):
        if dashboard and dashboard.mode == "preview":
            raise Forbidden("Upload documents in your personal workspace")
        store.get_case(tenant, case_id)
        if body.media_type not in {"application/pdf", "text/plain", "text/csv", "application/json", "image/png", "image/jpeg", "image/webp", "image/tiff"}:
            raise HTTPException(422, "Supported documents: PDF, plain text, CSV, JSON, PNG, JPEG, WebP and TIFF")
        if any(not isinstance(body.rights.get(k), bool) for k in ("process", "display_raw", "display_derived", "retain_raw")):
            raise HTTPException(422, "Explicit process/display_raw/display_derived/retain_raw rights are required")
        if body.rights["retain_raw"] is not True:
            raise HTTPException(422, "Document upload requires permission to retain its bytes")
        try:
            content = base64.b64decode(body.content_base64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise HTTPException(422, "Invalid base64 document") from exc
        if not content or len(content) > 5_000_000:
            raise HTTPException(413, "Document must contain 1 byte to 5 MB")
        filename = Path(body.filename.replace("\\", "/")).name
        if not filename or any(ord(c) < 32 for c in filename):
            raise HTTPException(422, "Document filename must be printable")
        digest = hashlib.sha256(content).hexdigest()
        document_id = "document-" + hashlib.sha256((tenant + "\0" + case_id + "\0" + digest).encode()).hexdigest()
        folder = directory / "documents" / hashlib.sha256(tenant.encode()).hexdigest()[:24] / hashlib.sha256(case_id.encode()).hexdigest()[:24]
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / digest
        # A server-generated path prevents directory traversal through filenames.
        target.write_bytes(content)
        try:
            target.chmod(0o600)
        except OSError:
            pass
        snapshot = {"document_id": document_id, "snapshot_id": document_id, "source_id": "private-document", "status": "CAPTURED",
                    "rights": body.rights, "filename": filename,
                    "media_type": body.media_type, "raw_files": [str(target)], "sha256": digest,
                    "bytes": len(content), "extraction_status": "NOT_ASSESSED",
                    "note": "Stored as evidence only. Document text cannot change rules or execute actions."}
        saved = store.add_document(tenant, case_id, snapshot)
        return document_metadata(saved)

    @app.get("/v1/cases/{case_id}/documents")
    def documents(case_id: str, tenant: str = Depends(auth)):
        return {"documents": [document_metadata(s) for s in store.list_documents(tenant, case_id)]}

    def document_file(tenant, document_id, case_id=None):
        snapshot = store.get_document(tenant, document_id, case_id=case_id, require_raw=True)
        target = Path(snapshot["raw_files"][0]).resolve()
        allowed = (directory / "documents").resolve()
        if not target.is_relative_to(allowed) or not target.is_file():
            raise HTTPException(404, "Document unavailable")
        if hashlib.sha256(target.read_bytes()).hexdigest() != snapshot["sha256"]:
            raise HTTPException(409, "Document hash does not match the captured snapshot")
        return FileResponse(target, media_type="application/octet-stream", filename=snapshot["filename"], content_disposition_type="attachment")

    @app.get("/v1/cases/{case_id}/documents/{document_id}")
    def download_document(case_id: str, document_id: str, tenant: str = Depends(auth)):
        return document_file(tenant, document_id, case_id)

    @app.get("/v1/documents/{document_id}/download")
    def download_document_by_id(document_id: str, tenant: str = Depends(auth)):
        return document_file(tenant, document_id)

    web = Path(__file__).resolve().parents[2] / "web"
    if web.is_dir():
        app.mount("/static", StaticFiles(directory=web), name="static")

    @app.get("/weekend", response_class=HTMLResponse, include_in_schema=False)
    def weekend_page():
        return FileResponse(web / "weekend.html", media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index():
        page = web / "index.html"
        if page.is_file():
            content = page.read_text(encoding="utf-8")
            if dashboard:
                content = content.replace('data-access="bearer"', f'data-access="{dashboard.mode}"')
            if dashboard and dashboard.mode == "preview":
                content = content.replace("LOCAL EVIDENCE WORKSPACE", "LOCAL DEMO · USE SAMPLE DATA ONLY")
            return HTMLResponse(content)
        return HTMLResponse('<!doctype html><html lang="en"><title>Property Risk Engine</title><h1>Property Risk Engine</h1><p>Open <a href="/docs">the API documentation</a> and authorise using your local bearer key.</p></html>')

    return app
