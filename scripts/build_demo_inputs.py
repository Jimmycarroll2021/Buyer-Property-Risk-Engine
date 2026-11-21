"""Rebuild transparent synthetic fixtures; never fetch real property evidence."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
case = json.loads((ROOT / "examples/case.json").read_text())
subject = case["property"]["parcel_geometry"]
def rect(x0, y0, x1, y1):
    return {"type":"Polygon", "coordinates":[[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]]}
def observation(check, name, payload, private=False):
    source = "synthetic-" + name
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return {"observation_id":f"demo-{check}-{name}","check_id":check,"property_id":case["property_id"],
        "source_id":source,"snapshot_id":"sha256:"+digest,"published_at":"2026-10-01T00:00:00Z",
        "received_at":"2026-10-02T00:00:00Z","evidence_basis":"reviewed_document" if private else "official_record",
        "confidence":"High","visibility_scope":"private" if private else "public",
        "owner_tenant_id":"demo" if private else None,"case_scope_id":case["case_id"] if private else None,
        "rights":{"process":True,"retain_raw":True,"display_raw":True,"display_derived":True},
        "quality":{"retrieval_status":"SUCCESS","coverage_status":"COVERED","complete":True,"current":True,"identity_match":True},
        "payload":payload,"demonstration":True,"source_note":"Invented demonstration evidence; not an actual government record."}

rows = [
observation("S005","flood",{"kind":"spatial","subject_geometry":subject,"hazard_geometry":rect(690010,6080010,690040,6080040),"crs":"EPSG:7855","positional_uncertainty_m":0,"mechanism":"riverine_flood"}),
observation("S006","flood-boundary",{"kind":"spatial","subject_geometry":subject,"hazard_geometry":rect(690020,6080000,690040,6080020),"crs":"EPSG:7855","positional_uncertainty_m":0.5,"mechanism":"flood_boundary"}),
observation("S011","bushfire",{"kind":"spatial","subject_geometry":subject,"hazard_geometry":rect(690100,6080100,690200,6080200),"crs":"EPSG:7855","positional_uncertainty_m":1,"mechanism":"bushfire"}),
observation("S021","inspection",{"kind":"inspection","reviewed":True,"material_defect":True,"cost_known":False,"statement":"Synthetic inspection reports a structural concern requiring an engineer and repair quote."},True),
observation("S025","insurance",{"kind":"insurance","reviewed":True,"conflict":False,"material_exclusion":True,"statement":"Synthetic insurance quote excludes a material flood mechanism; cover needs review."},True),
observation("S035","transport",{"kind":"opportunity","project_id":"synthetic-rail-project","benefit":"A proposed station could shorten the reviewed journey to the buyer's workplace.","benefit_supported":True,"timing_known":True,"expected_completion":"2029-12-01T00:00:00Z","dependencies":["Funded construction and opening","Verified walk access"],"milestones":[{"kind":"announced","date":"2026-01-01T00:00:00Z","published_at":"2026-01-01T00:00:00Z"},{"kind":"approved","date":"2026-09-01T00:00:00Z","published_at":"2026-09-01T00:00:00Z"}]}),
observation("S037","supply",{"kind":"project","project_id":"synthetic-apartment-project","net_dwellings":60,"scope_comparable":True,"declared_net_dwellings_threshold":50,"expected_completion":"2028-06-01T00:00:00Z","milestones":[{"kind":"approved","date":"2026-05-01T00:00:00Z","published_at":"2026-05-01T00:00:00Z"}]}),
observation("S048","crime",{"kind":"context","summary":"Synthetic area-level property-offence measure","count":120,"denominator":10000,"rate_base":1000,"period_start":"2025-01-01T00:00:00Z","period_end":"2026-01-01T00:00:00Z","area_id":"synthetic-area","boundary_version":"synthetic-v1","definition":"Recorded property offences, synthetic fixture","comparable":True}),
observation("S055","rates",{"kind":"context","summary":"The loan uses the buyer's entered rate; macro policy-rate context is separate.","measure":"6.00","unit":"percent_per_year","definition":"Synthetic borrower loan interest rate; not a current RBA cash rate."},True),
]
(ROOT / "examples/observations.json").write_text(json.dumps(rows, indent=2)+"\n", encoding="utf-8")
(ROOT / "examples/reviewed_observation_template.json").write_text(json.dumps({
    "observation_id":"REPLACE-UNIQUE-OBSERVATION-ID","check_id":"S021","property_id":"REPLACE-PROPERTY-ID",
    "source_id":"private-inspection","snapshot_id":"REPLACE-DOCUMENT-SNAPSHOT-ID","published_at":None,
    "evidence_basis":"reviewed_document","confidence":"Medium","visibility_scope":"private",
    "rights":{"process":True,"retain_raw":True,"display_raw":True,"display_derived":True},
    "quality":{"retrieval_status":"SUCCESS","coverage_status":"UNKNOWN","complete":False,"current":False,"identity_match":False},
    "payload":{"kind":"inspection","reviewed":False,"material_defect":None,"scope_complete":False,"statement":"Replace with a reviewed, page-referenced observation."}
},indent=2)+"\n",encoding="utf-8")
