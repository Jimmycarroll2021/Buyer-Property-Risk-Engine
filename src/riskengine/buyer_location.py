"""ACT address matching and location identity for the buyer dashboard."""
from __future__ import annotations

from datetime import datetime, time, timezone
from functools import lru_cache
import json
import math
import re

import httpx
from shapely.geometry import Point, shape

from .paths import project_root


ADDRESS_LAYER = "https://services1.arcgis.com/E5n4f1VY84i0xSjy/arcgis/rest/services/ACTGOV_ADDRESSES/FeatureServer/0"
ADDRESS_FIELDS = "ADDRESS_ID,DOOR_NO,STREET_NUMBER,STREET_NAME,STREET_TYPE,DIVISION,LAT,LONG"
STREET_TYPES = {"ST": "STREET", "RD": "ROAD", "AVE": "AVENUE", "CRES": "CRESCENT",
                "PL": "PLACE", "CT": "COURT", "DR": "DRIVE", "CCT": "CIRCUIT", "PDE": "PARADE"}


def coordinates(latitude, longitude):
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return None
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


def address_point(attributes):
    point = coordinates(attributes.get("LAT"), attributes.get("LONG"))
    if not point or not attributes.get("DIVISION") or not attributes.get("ADDRESS_ID"):
        return None
    number = attributes["STREET_NUMBER"]
    if attributes.get("DOOR_NO"):
        number = f"{attributes['DOOR_NO']}/{number}"
    suburb = attributes["DIVISION"].title()
    street = f"{attributes['STREET_NAME']} {attributes['STREET_TYPE']}".title()
    address_id = int(attributes["ADDRESS_ID"])
    return {"label": f"{number} {street}, {suburb} ACT", "suburb": suburb,
            "latitude": point[0], "longitude": point[1], "address_id": address_id,
            "source_url": f"{ADDRESS_LAYER}/query?where=ADDRESS_ID%3D{address_id}&outFields=*&returnGeometry=false&f=pjson"}


def kingston_location():
    path = project_root() / "config/kingston_example_address.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["ADDRESS_ID"] != 793201:
        raise ValueError("The retained Kingston example has an unexpected address ID")
    location = address_point(record)
    return {**location, "basis": "Retained ACT Government address point", "source_date": "2026-11-21"}


@lru_cache(maxsize=1)
def division_boundaries(path):
    layer = json.loads(path.read_text(encoding="utf-8"))
    polygons = [(f["properties"]["DIVISION_NAME"], shape(f["geometry"])) for f in layer["features"]]
    return polygons, layer["source_url"], layer["attribution"], layer["retrieved_at"]


def locality_key(value):
    return re.sub("[^A-Z0-9]", "", str(value or "").upper())


def location_for_case(case):
    prop = case.get("property") or {}
    point = coordinates(prop.get("latitude"), prop.get("longitude"))
    suburb = prop.get("suburb") or prop.get("division")
    if not isinstance(suburb, str):
        suburb = None
    location = {"label": prop.get("label") or case["property_id"], "suburb": suburb,
                "latitude": point[0] if point else None, "longitude": point[1] if point else None,
                "basis": "Location recorded in this case", "source_url": None}
    case_location = location
    cutoff = None
    if case.get("as_of"):
        cutoff = datetime.fromisoformat(case["as_of"])
        if len(case["as_of"]) == 10:
            cutoff = datetime.combine(cutoff.date(), time.max, tzinfo=timezone.utc)
    jurisdiction = locality_key(prop.get("jurisdiction"))
    state = locality_key(prop.get("state") or jurisdiction)
    act_names = {"ACT", "AUSTRALIANCAPITALTERRITORY"}
    if jurisdiction not in act_names or state not in act_names:
        return {**location, "issue": "An ACT jurisdiction must be recorded for the ACT location sources."}
    if point is None and (prop.get("latitude") is not None or prop.get("longitude") is not None):
        return {**location, "issue": "The recorded address coordinates are invalid or incomplete."}
    if str(prop.get("address_id")) == "793201":
        known = kingston_location()
        if cutoff and cutoff.astimezone(timezone.utc).date().isoformat() < known["source_date"]:
            return {**case_location, "issue": "The retained ACT address point postdates this assessment."}
        label = str(prop.get("label") or "").upper()
        conflicting_label = bool(re.match(r"^(?:UNIT\s+)?\d", label)) and (
            "CURRIE" not in label or not re.search(r"\b14\b", label)
            or (re.search(r"\d+\s*/", label) and not re.search(r"\b11\s*/\s*14\b", label)))
        if (suburb and locality_key(suburb) != "KINGSTON"
                or point and (abs(point[0]-known["latitude"]) > 0.0001 or abs(point[1]-known["longitude"]) > 0.0001)
                or prop.get("unit_id") is not None and str(prop["unit_id"]) != "11" or conflicting_label):
            return {**location, "issue": "The stored suburb, address or coordinates conflict with ACT address ID 793201."}
        location = known
        suburb = known["suburb"]
        point = known["latitude"], known["longitude"]
    if point:
        polygons, source, attribution, retrieved = division_boundaries(project_root() / "config/act_address_divisions.geojson")
        if cutoff and cutoff < datetime.fromisoformat(retrieved):
            return {**case_location, "issue": "The saved ACT suburb boundary evidence was captured after this assessment date.",
                    "division_source_url": source, "division_retrieved_at": retrieved}
        match = [name for name, polygon in polygons if polygon.covers(Point(point[1], point[0]))]
        if len(match) != 1:
            return {**location, "issue": "The point does not resolve to one mapped ACT suburb in the saved division boundaries."}
        if suburb and locality_key(suburb) != locality_key(match[0]):
            return {**location, "issue": "The recorded suburb and coordinates disagree with the ACT division boundary."}
        location.update(suburb=match[0].title(), division_source_url=source, division_attribution=attribution,
                        division_retrieved_at=retrieved)
    # A stored id provides a stable link to verify coordinates against the publisher.
    address_id = str(prop.get("address_id", ""))
    if re.fullmatch(r"[0-9]{1,10}", address_id):
        location["source_url"] = f"{ADDRESS_LAYER}/query?where=ADDRESS_ID%3D{address_id}&outFields=*&returnGeometry=false&f=pjson"
    return location


def lookup_addresses(street, suburb):
    street = " ".join(street.upper().split())
    suburb = " ".join(suburb.upper().split())
    match = re.fullmatch(r"(?:(\d+[A-Z]?)/)?(\d+[A-Z]?(?:-\d+[A-Z]?)?) ([A-Z][A-Z '-]*?) ([A-Z]+)", street)
    if not match or not re.fullmatch(r"[A-Z][A-Z '-]{0,79}", suburb):
        raise ValueError("Enter the street number, full street name and suburb. Include the unit as 11/14.")
    unit, number, name, kind = match.groups()
    fields = {"STREET_NUMBER": number, "STREET_NAME": name, "STREET_TYPE": STREET_TYPES.get(kind, kind), "DIVISION": suburb}
    if unit:
        fields["DOOR_NO"] = unit
    terms = []
    for field, value in fields.items():
        literal = value.replace("'", "''")
        terms.append(f"{field}='{literal}'")
    where = " AND ".join(terms)
    response = httpx.get(f"{ADDRESS_LAYER}/query", params={"where": where, "outFields": ADDRESS_FIELDS,
                         "returnGeometry": "false", "resultRecordCount": 20, "orderByFields": "ADDRESS_ID", "f": "json"},
                         timeout=6)
    response.raise_for_status()
    body = response.json()
    if "features" not in body:
        raise RuntimeError("The address register could not complete this search")
    matches = [address_point(feature["attributes"]) for feature in body["features"]]
    return {"matches": [item for item in matches if item], "truncated": bool(body.get("exceededTransferLimit"))}


def example_case():
    sample = json.loads((project_root() / "examples/case.json").read_text(encoding="utf-8"))
    location = kingston_location()
    return {"case_id": "kingston-buyer-example", "property_id": "act-address-793201",
            "property": {"jurisdiction": "ACT", "property_type": "unit", "unit_id": "11",
                         "identity_confirmed": False, **{key:location[key] for key in ("label", "latitude", "longitude", "suburb", "address_id")}},
            "as_of": datetime.now(timezone.utc).isoformat(), "assessment_mode": "buyer_assessment",
            "finance_is_illustrative": True, "finance": sample["finance"], "requirements": sample["requirements"],
            "scenarios": sample["scenarios"], "input_note": "Public ACT address. All buyer amounts and purchase terms are illustrative."}
