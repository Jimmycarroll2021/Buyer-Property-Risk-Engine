"""Offline observations for the public ACT address 793201, with retained source receipts."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from decimal import Decimal

from shapely.geometry import box, mapping, shape

from .buyer_location import location_for_case
from .nearby_planning import planning_signals
from .paths import project_root


def _config(filename):
    return json.loads((project_root() / "config" / filename).read_bytes())


def _pack():
    pack = _config("kingston_public_evidence.json")
    for source, receipt in pack.items():
        raw = (json.dumps(receipt["data"], separators=(",", ":"), ensure_ascii=False)
               if "data" in receipt else receipt["csv"])
        if hashlib.sha256(raw.encode()).hexdigest() != receipt["response_sha256"]:
            raise ValueError(f"Retained source checksum mismatch for {source}")
    return pack


def _attrs(snapshot):
    return [f["attributes"] for f in snapshot["data"]["features"]]


def _instant(value):
    if len(value) == 10:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError("A timezone-aware sample cutoff is required")
    return value.astimezone(timezone.utc)


def kingston_public_identity():
    """Verified public case attributes; registered unit polygons are not building outlines."""
    pack = _pack()
    address, = _attrs(pack["act_addresses"])
    block, = pack["act_blocks"]["data"]["features"]
    unit = _attrs(pack["act_unit"])
    key = address["BLOCK_KEY"]
    if not (
        address["ADDRESS_ID"] == 793201 and address["ASSIGNED"] == "ASSIGNED"
        and address["DIVISION"] == "KINGSTON" and address["SUBADDTYPE"] == "Unit"
        and address["UNIT_TITLE"] == address["DOOR_NO"] == "11"
        and block["properties"]["BLOCK_KEY"] == key == 12170240009
        and block["properties"]["CURRENT_LIFECYCLE_STAGE"] == "REGISTERED"
        and {(u["BLOCK_KEY"], u["UNIT_NUMBER"], u["UNIT_PLAN_NO"], u["UNIT_CLASS"],
              u["CURRENT_LIFECYCLE_STAGE"], u["ID"]) for u in unit}
        == {(key, "11", address["UNITPLAN_NO"], address["UNIT_CLASS"], "REGISTERED", 19672)}
    ):
        raise ValueError("The retained address, parcel and unit registers disagree")
    return {"address_id": address["ADDRESS_ID"], "block_key": key, "unit_id": "11",
            "units_plan_no": address["UNITPLAN_NO"], "unit_class": address["UNIT_CLASS"],
            "block": block["properties"]["BLOCK_NUMBER"], "section": block["properties"]["SECTION_NUMBER"],
            "division": "KINGSTON", "unit_required": True, "property_type": "unit",
            "ownership_form": "unit_title", "parcel_geometry": block["geometry"], "crs": "EPSG:7855",
            "identity_confirmed": True}


def _file_receipt(name, url, attribution, known):
    data = (project_root() / "config" / name).read_bytes()
    return {"query_url": url, "attribution": attribution, "retrieved_at": known,
            "response_sha256": hashlib.sha256(data).hexdigest(), "captured_file": name}


def build_kingston_public_evidence(case):
    """Build immutable evidence for the known public example, with partial scopes explicitly gated."""
    prop = case.get("property", {})
    identity = kingston_public_identity()
    if (case.get("property_id") not in {"act-address-793201", "act:block-12170240009:unit-11"}
            or str(prop.get("address_id")) != "793201" or str(prop.get("unit_id")) != "11"
            or prop.get("identity_confirmed") is not True or prop.get("ambiguous")
            or location_for_case(case).get("issue")):
        return []
    if prop.get("property_type") not in (None, "unit", "townhouse") or any(
           str(prop[k]).casefold() != str(identity[k]).casefold()
           for k in ("block_key", "units_plan_no", "unit_class", "ownership_form",
                     "division", "block", "section") if k in prop):
        return []
    if prop.get("parcel_geometry") is not None and (prop.get("crs") != identity["crs"]
            or not shape(prop["parcel_geometry"]).equals(shape(identity["parcel_geometry"]))):
        return []
    pack = _pack()
    known = max(pack[k]["retrieved_at"] for k in ("act_addresses", "act_blocks", "act_unit"))
    if _instant(case["as_of"]) < _instant(known):
        return []
    rows = []

    def add(check, source, payload, receipts, *, complete=True, dependencies=()):
        cutoff = max([known] + [r["retrieved_at"] for r in receipts])
        if _instant(cutoff) > _instant(case["as_of"]):
            return
        refs = [{k: r[k] for k in ("query_url", "response_sha256", "attribution", "retrieved_at")}
                for r in receipts]
        digest = hashlib.sha256(json.dumps(refs, sort_keys=True).encode()).hexdigest()
        body = {"check_id": check, "source_id": source, "property_id": case["property_id"],
                "snapshot_id": "sha256:" + (refs[0]["response_sha256"] if len(refs) == 1 else digest),
                "published_at": cutoff, "evidence_basis": "official_record", "confidence": "Medium",
                "visibility_scope": "public", "owner_tenant_id": None, "case_scope_id": None,
                "rights": dict.fromkeys(("process", "retain_raw", "display_raw", "display_derived"), True),
                "quality": {"retrieval_status": "SUCCESS", "coverage_status": "COVERED",
                            "complete": complete, "current": True, "identity_match": True},
                "public_sources": refs, "source_ids": sorted({source, "act_addresses", "act_blocks", "act_unit",
                                                              "act_boundary", *dependencies}),
                "knowledge_date_basis": "Conservative retained-evidence cutoff",
                "payload": payload}
        suffix = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:24]
        rows.append({"observation_id": "kingston-" + check + "-" + suffix, **body})

    for source in ("act_addresses", "act_unit"):
        add("S002", source, {"kind": "unit_register", "records": _attrs(pack[source])}, [pack[source]])

    parcel = identity["parcel_geometry"]
    coverage = box(694240, 6089620, 694725, 6090100)
    bushfire = pack["act_bushfire_2026"]
    if bushfire["data"].get("objectIds") == [] and coverage.contains(shape(parcel).buffer(200)):
        add("S011", "act_bushfire_2026",
            {"kind": "spatial", "subject_scope": "registered parent parcel, published 2026 designation only",
             "subject_geometry": parcel, "crs": "EPSG:7855", "coverage_geometry": mapping(coverage),
             "hazard_geometry": {"type": "GeometryCollection", "geometries": []},
             "positional_uncertainty_m": 200, "mechanism": "bushfire",
             "coverage_basis": "ACT-wide 2026 designation queried for all IDs within the parcel envelope expanded by at least 200 m. This is a tested spatial margin, not an estimate of survey error or personal fire risk.",
             "designation_scope_url": "https://esa.act.gov.au/be-emergency-ready/bushfires"},
            [bushfire, pack["act_blocks"]])

    people = _config("nearby_crime_population.json")
    population = people["areas"]["KINGSTON"]
    pop_ref = _file_receipt("nearby_crime_population.json", people["source_url"], people["attribution"], known)
    before, after = population["erp_2024"], population["erp_2025"]
    add("S041", "abs_regional_population",
        {"kind": "context", "summary": f"Kingston SA2 801061131 had {before:,} estimated residents in June 2024 and {after:,} in June 2025. The ABS 2024–25 regional population release is dated 31 March 2026. This is historical regional change.",
         "measure": after-before, "unit": "persons", "definition": "Difference between like-boundary annual ABS resident population estimates."},
        [pop_ref], dependencies=("canberra_dem01",))
    crime = _config("nearby_crime.json")
    crime_ref = _file_receipt("nearby_crime.json", crime["asset_url"], crime["attribution"], known)
    for offence, counts in crime["areas"]["KINGSTON"].items():
        if offence == "district":
            continue
        add("S048", "act_crime_statistics", {"kind": "context", "count": counts[1],
            "denominator": (before + after) / 2, "rate_base": 1000,
            "period_start": "2024-07-01", "period_end": "2025-06-30", "area_id": "KINGSTON",
            "boundary_version": f"ACT Policing suburb; ABS 2021 SAL {population['sal']} and SA2 {population['sa2']} share {population['mesh_blocks']} mesh blocks",
            "definition": f"{offence}, ACT Policing. Prior financial year count {counts[0]}. Historical recorded offences (including visitors); small counts fluctuate. Rate uses the mean June 2024 and 2025 estimated population.",
            "factor_id": offence, "comparable": True}, [crime_ref, pop_ref],
            dependencies=("abs_regional_population", "canberra_crm01", "canberra_dem01"))

    approvals = pack["abs_building_approvals"]
    stock = pack["abs_census_2021_dwellings"]
    months = {r["TIME_PERIOD"]: int(r["OBS_VALUE"]) for r in csv.DictReader(io.StringIO(approvals["csv"]))
              if (r["REGION"], r["MEASURE"], r["BUILDING_TYPE"], r["WORK_TYPE"]) == ("801061131", "1", "100", "1")}
    periods = {f"{y}-{m:02}" for y in (2024, 2025, 2026) for m in range(1, 13)
               if "2024-10" <= f"{y}-{m:02}" <= "2026-09"}
    dwellings, = [int(r["OBS_VALUE"]) for r in csv.DictReader(io.StringIO(stock["csv"]))
                  if (r["REGION"], r["TIME_PERIOD"], r["DWTSTRD"], r["SUM"]) == ("801061131", "2021", "_T", "D")]
    if months.keys() == periods and dwellings > 0:
        newest = sum(v for m, v in months.items() if m >= "2025-10")
        prior = sum(months.values()) - newest
        add("S038", "abs_building_approvals", {"kind": "context", "measure": str(Decimal(newest)*1000/dwellings),
            "unit": "approvals per 1,000 dated private dwellings",
            "definition": "All residential types; October 2025–September 2026 approvals over 2021 Census stock in Kingston SA2 801061131.",
            "summary": f"ABS recorded {newest} new dwelling approvals in the 12 months to September 2026, after {prior} in the previous 12 months. The same Kingston SA2 recorded {dwellings:,} total private dwellings in the 2021 Census. The denominator predates the approvals; these are approvals across dwelling types, not completed units."}, [approvals, stock],
            dependencies=("abs_census_2021_dwellings",))

    address = _attrs(pack["act_addresses"])[0]
    planning = _config("nearby_planning.json")
    for signal in planning_signals(float(address["LAT"]), float(address["LONG"]), case["as_of"]):
        is_da = "DA " in signal["title"]
        file = "nearby_planning_data/application_blocks.geojson" if is_da else "nearby_planning.json"
        ref = _file_receipt(file, signal["source_url"], signal["attribution"], known)
        source_refs = [ref]
        if is_da:
            source_refs.append(_file_receipt("nearby_planning.json", planning["da"]["status_source"], signal["attribution"], known))
        add("S030" if is_da else "S034", "act_da_active" if is_da else "act_light_rail_stage_2b",
            {"kind": "context", "summary": signal["title"] + ". " + signal["detail"],
             "fact_key": signal["title"], "reference_period": signal["as_of"], "coverage": signal["coverage"]},
            source_refs, complete=False, dependencies=("act_da_finder",) if is_da else ())

    schools = pack["act_schools_2026"]
    names = sorted(r["SCHOOL_NAME"] + " (" + r["YEAR_LEVEL"] + ")" for r in _attrs(schools))
    add("S049", "act_schools_2026", {"kind": "context",
        "summary": "2026 PEA polygons at address 793201: " + ", ".join(names) + ". Shared primary zone; buyer school requirements and enrolment fit are unresolved."}, [schools], complete=False)
    canopy = pack["act_canopy_2020"]
    c, = _attrs(canopy)
    if c["BLOCK_KEY"] == identity["block_key"]:
        add("S053", "act_canopy_2020", {"kind": "context",
            "summary": f"2020 survey: {c['F_2020_CANOPY_COVER_PERCENTAGE']}% canopy across Block 9 ({c['F_2020_CANOPY_AREA']} m²). Shade at Unit 11 and subsequent changes are unknown."}, [canopy], complete=False)
    return rows
