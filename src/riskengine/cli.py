"""Local administrator commands. Credentials are never built into the package."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
from .paths import data_root, project_root
from .preoffer_assessment import buyer_first
from .storage import Store, StoreError

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")

def initialise(directory, tenant="demo"):
    directory.mkdir(parents=True, exist_ok=True)
    try: directory.chmod(0o700)
    except OSError: pass
    keyfile = directory / "api_keys.json"
    if not keyfile.exists():
        fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump({secrets.token_urlsafe(36): tenant}, out, indent=2)
            out.write("\n")
    Store(directory / "riskengine.sqlite3")
    return {"data_directory": str(directory), "api_key_file": str(keyfile), "dashboard": "http://127.0.0.1:8000"}

def _parser():
    p = argparse.ArgumentParser(prog="property-risk", description="Deterministic property evidence and buyer assessment")
    p.add_argument("--data-dir", help="Private runtime directory (default runtime/)")
    p.add_argument("--tenant", default="demo", help="Local administrator tenant scope")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create local database and a random API token")
    sub.add_parser("token", help="Print this tenant's local API token; do not share it")
    sub.add_parser("demo", help="Load synthetic inputs and write an example assessment")
    s = sub.add_parser("serve", help="Start local authenticated dashboard/API")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8000)
    mode = s.add_mutually_exclusive_group()
    mode.add_argument("--desktop", action="store_true", help="Open this single-user workspace in your browser")
    mode.add_argument("--sample-preview", action="store_true", help="Open access to the dedicated loopback sample workspace")
    s = sub.add_parser("import-case", help="Create a versioned purchase case from JSON")
    s.add_argument("path"); s.add_argument("--expected-version", type=int)
    s = sub.add_parser("import-observations", help="Import structured, reviewed observation JSON")
    s.add_argument("case_id"); s.add_argument("path")
    s.add_argument("--trusted-public", action="store_true", help="Administrator-only public evidence import")
    s = sub.add_parser("assess", help="Assess captured evidence with the fixed check catalogue")
    s.add_argument("case_id"); s.add_argument("--output", default="runtime/assessment.json")
    s.add_argument("--advance-as-of", action="store_true", help="Explicitly create a case version with current knowledge time")
    s = sub.add_parser("preoffer", help="Start an ACT pre-offer assessment with an address and buyer-entered price")
    s.add_argument("--street", required=True, help="Include the unit number where applicable")
    s.add_argument("--suburb", required=True)
    s.add_argument("--offer-price", required=True, help="AUD asking price or proposed offer")
    s.add_argument("--address-id", help="Select the exact register ID if the search returns multiple matches")
    s.add_argument("--case-id", help="Optional new case ID")
    s.add_argument("--price-basis", choices=["asking", "proposed_offer"], default="proposed_offer")
    s.add_argument("--intended-use", choices=["owner_occupier"], default="owner_occupier")
    s.add_argument("--buyer-inputs", help="Private JSON containing finance, buyer_protection and optional preoffer scenario inputs")
    s.add_argument("--output", default="runtime/preoffer-assessment.json")
    s = sub.add_parser("replay", help="Verify an immutable assessment against its pinned inputs")
    s.add_argument("assessment_id")
    sub.add_parser("sources", help="List configured source IDs, adapters and activation status")
    s = sub.add_parser("collect", help="Capture one configured source with explicit scope limits")
    s.add_argument("case_id"); s.add_argument("source_id"); s.add_argument("--bounds", help="JSON file with bounded query fields")
    s.add_argument("--max-records", type=int, default=1000); s.add_argument("--max-bytes", type=int, default=20_000_000)
    s.add_argument("--enqueue", action="store_true"); s.add_argument("--idempotency-key")
    s = sub.add_parser("worker", help="Process available persisted jobs")
    s.add_argument("--max-jobs", type=int, default=10)
    sub.add_parser("jobs", help="Show durable collection job states")
    s = sub.add_parser("review", help="Append a review without mutating the finding")
    s.add_argument("assessment_id"); s.add_argument("action", choices=["acknowledged", "waived", "investigate", "resolution_submitted"])
    s.add_argument("note"); s.add_argument("--finding-id")
    s = sub.add_parser("source-policy", help="Restrict permissions on captured evidence")
    s.add_argument("source_id"); s.add_argument("path", help="JSON object of explicit rights booleans")
    return p

def main(argv=None):
    args = _parser().parse_args(argv)
    directory = data_root(args.data_dir).resolve()
    try:
        if args.command == "init": result = initialise(directory, args.tenant)
        elif args.command == "token":
            values = read_json(directory / "api_keys.json")
            matches = [k for k, v in values.items() if v == args.tenant]
            if not matches: raise ValueError("No token for this tenant; run init or configure a key file")
            print(matches[0]); return 0
        elif args.command == "serve":
            import uvicorn
            from .api import create_app
            if args.desktop or args.sample_preview:
                from .desktop import LocalDashboard
                dashboard = LocalDashboard("desktop" if args.desktop else "preview", args.host, args.port,
                                           args.tenant, directory)
                app = create_app(data_dir=directory, dashboard=dashboard)
                config = uvicorn.Config(app, host=args.host, port=args.port, proxy_headers=False)

                class DashboardServer(uvicorn.Server):
                    async def startup(self, sockets=None):
                        await super().startup(sockets)
                        if self.started and args.desktop:
                            dashboard.open_browser()

                try:
                    DashboardServer(config).run()
                finally:
                    dashboard.close()
            else:
                uvicorn.run(create_app(data_dir=directory), host=args.host, port=args.port)
            return 0
        elif args.command == "sources":
            from .ingestion import load_registry
            result = [{k: r.get(k) for k in ("source_id", "title", "adapter", "enabled", "licence_status", "access_status")} for r in load_registry()]
        else:
            from .pipeline import assess_case, collect_case, enqueue_collection, import_observations, work_once
            from .reporting import render_assessment
            store = Store(directory / "riskengine.sqlite3")
            if args.command == "demo":
                initialise(directory, args.tenant)
                case = read_json(project_root() / "examples/case.json"); case["owner_tenant_id"] = args.tenant
                store.save_case(args.tenant, case)
                observations = read_json(project_root() / "examples/observations.json")
                for row in observations:
                    if row["visibility_scope"] == "private": row["owner_tenant_id"] = args.tenant
                import_observations(store, args.tenant, case["case_id"], observations, trusted_public=True, preserve_received_at=True)
                assessment = assess_case(store, args.tenant, case["case_id"])
                write_json(directory / "demo-assessment.json", buyer_first(assessment))
                (directory / "demo-report.html").write_text(render_assessment(assessment), encoding="utf-8")
                result = {"case_id": case["case_id"], "assessment_id": assessment["assessment_id"], "status": assessment["status"],
                          "coverage": assessment["coverage"], "report": str(directory / "demo-report.html"),
                          "note": "Synthetic demonstration. Missing checks remain visible."}
            elif args.command == "import-case": result = store.save_case(args.tenant, read_json(args.path), args.expected_version)
            elif args.command == "import-observations":
                records = import_observations(store, args.tenant, args.case_id, read_json(args.path), trusted_public=args.trusted_public)
                result = {"imported": len(records), "observation_ids": [r["observation_id"] for r in records],
                          "note": "Private receipt time is now; advance case as_of explicitly to include new evidence."}
            elif args.command in ("assess", "preoffer"):
                if args.command == "preoffer":
                    import httpx
                    from .preoffer_locations import lookup_addresses
                    if store.restricted_decision_sources(args.tenant, ("act_addresses",)):
                        raise StoreError("The ACT address register is restricted for this workspace")
                    try:
                        matches = lookup_addresses(args.street, args.suburb)["matches"]
                    except (httpx.HTTPError, RuntimeError) as exc:
                        raise StoreError("The ACT address register is unavailable for this search") from exc
                    if args.address_id:
                        matches = [m for m in matches if str(m["address_id"]) == args.address_id]
                    if len(matches) != 1:
                        choices = ", ".join(f"{m['address_id']} ({m['label']})" for m in matches)
                        raise ValueError(f"Select one ACT address with --address-id. Available matches: {choices or 'none'}")
                    point = matches[0]
                    case = {"property_id": f"act-address-{point['address_id']}",
                            "property": {**point, "jurisdiction": "ACT", "identity_confirmed": True},
                            "as_of": datetime.now(timezone.utc).isoformat(),
                            "preoffer": {"offer_price": args.offer_price, "intended_use": args.intended_use,
                                         "price_basis": args.price_basis}}
                    if args.buyer_inputs:
                        inputs = read_json(args.buyer_inputs)
                        if not isinstance(inputs, dict) or set(inputs) - {"finance", "buyer_protection", "preoffer", "finance_is_illustrative"}:
                            raise ValueError("Buyer inputs must contain only finance, buyer_protection, preoffer or finance_is_illustrative")
                        options = inputs.pop("preoffer", {})
                        if not isinstance(options, dict):
                            raise ValueError("preoffer must be an object")
                        case.update(inputs)
                        case["preoffer"] = {**options, **case["preoffer"]}
                    if args.case_id:
                        case["case_id"] = args.case_id
                    args.case_id = store.save_case(args.tenant, case, expected_version=0)["case_id"]
                elif args.advance_as_of:
                    case = store.get_case(args.tenant, args.case_id); case["as_of"] = datetime.now(timezone.utc).isoformat()
                    store.save_case(args.tenant, case, case["case_version"])
                result = assess_case(store, args.tenant, args.case_id)
                write_json(args.output, buyer_first(result))
                Path(args.output).with_suffix(".html").write_text(render_assessment(result), encoding="utf-8")
                result = {"buyer_summary": result["buyer_summary"], "case_id": args.case_id, "assessment_id": result["assessment_id"], "status": result["status"],
                          "json": str(Path(args.output).resolve()), "report": str(Path(args.output).with_suffix(".html").resolve())}
            elif args.command == "replay":
                from .engine import canonical_hash
                from .pipeline import replay_assessment
                saved, replayed = replay_assessment(store, args.tenant, args.assessment_id)
                equal = canonical_hash(saved) == canonical_hash(replayed)
                result = {"assessment_id": args.assessment_id, "exact_match": equal,
                          "saved_result_hash": canonical_hash(saved), "replayed_result_hash": canonical_hash(replayed)}
                if not equal: print(json.dumps(result, indent=2)); return 2
            elif args.command == "collect":
                bounds = read_json(args.bounds) if args.bounds else None
                if args.enqueue:
                    if not args.idempotency_key: raise ValueError("--idempotency-key is required when enqueueing")
                    result = enqueue_collection(store, args.tenant, args.case_id, args.source_id, bounds=bounds,
                                                max_records=args.max_records, max_bytes=args.max_bytes, idempotency_key=args.idempotency_key)
                    result.pop("lease_token", None)
                else:
                    result = collect_case(store=store, tenant_id=args.tenant, case_id=args.case_id, source_id=args.source_id,
                                          output_dir=directory / "snapshots", bounds=bounds, max_records=args.max_records, max_bytes=args.max_bytes)
            elif args.command == "worker":
                if not 1 <= args.max_jobs <= 100: raise ValueError("--max-jobs must be between 1 and 100")
                result = []
                for _ in range(args.max_jobs):
                    job = work_once(store, directory / "snapshots", args.tenant)
                    if job is None: break
                    result.append(job)
            elif args.command == "jobs": result = store.list_jobs(args.tenant)
            elif args.command == "review": result = store.add_review(args.tenant, args.assessment_id, args.action, args.note, args.finding_id)
            elif args.command == "source-policy":
                store.set_source_policy(args.tenant, args.source_id, read_json(args.path))
                result = {"source_id": args.source_id, "status": "POLICY_UPDATED"}
            else: raise ValueError("Unknown command")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str)); return 0
    except (StoreError, ValueError, OSError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1

if __name__ == "__main__": raise SystemExit(main())
