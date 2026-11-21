"""Retained official ACT evidence for two exact unit addresses and bounded point queries."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import re

from pyproj import Transformer
from shapely.geometry import Point, shape

from . import buyer_location
from .kingston_public_evidence import build_kingston_public_evidence
from .paths import project_root


_IDENTITY_KEYS = ("address", "block", "unit")
_IDENTITY_SOURCES = ("act_addresses", "act_blocks", "act_unit", "act_boundary")
_MGA = Transformer.from_crs(4326, 7855, always_xy=True)


@lru_cache(maxsize=1)
def _register():
    pack = json.loads((project_root() / "config/preoffer_locations.json").read_bytes())
    for address_id, home in pack["homes"].items():
        for snapshot in home.values():
            raw = snapshot.pop("response_text")
            if hashlib.sha256(raw.encode()).hexdigest() != snapshot["response_sha256"]:
                raise ValueError("Retained ACT response checksum mismatch")
            snapshot["data"] = json.loads(raw)
            snapshot.update(pack["sources"][snapshot["source_id"]])
            if snapshot["data"].get("error") or snapshot["data"].get("exceededTransferLimit"):
                raise ValueError("Incomplete ACT response")
        address, = _attributes(home["address"])
        block, = home["block"]["data"]["features"]
        parcel = block["properties"]
        units = _attributes(home["unit"])
        if not (str(address["ADDRESS_ID"]) == address_id and address["ASSIGNED"] == "ASSIGNED"
                and address["SUBADDTYPE"] == "Unit" and address["DOOR_NO"] == address["UNIT_TITLE"]
                and address["DIVISION"] == parcel["DIVISION_NAME"]
                and address["BLOCK_KEY"] == parcel["BLOCK_KEY"]
                and parcel["CURRENT_LIFECYCLE_STAGE"] == "REGISTERED" and units
                and len({r["ID"] for r in units}) == 1
                and all((r["BLOCK_KEY"], r["UNIT_NUMBER"], r["UNIT_PLAN_NO"], r["UNIT_CLASS"],
                         r["CURRENT_LIFECYCLE_STAGE"]) == (address["BLOCK_KEY"], address["UNIT_TITLE"],
                         address["UNITPLAN_NO"], address["UNIT_CLASS"], "REGISTERED") for r in units)):
            raise ValueError("Ambiguous or conflicting ACT register identity")
        home["dwelling"] = pack["dwelling_descriptions"][address_id]
    return pack["homes"]


def _attributes(snapshot):
    return [f["attributes"] for f in snapshot["data"]["features"]]


@lru_cache(maxsize=1)
def _jardine_register():
    home = json.loads((project_root() / "config/jardine_register.json").read_bytes())
    for snapshot in home.values():
        raw = snapshot.pop("response_text")
        if hashlib.sha256(raw.encode()).hexdigest() != snapshot["response_sha256"]:
            raise ValueError("Retained Jardine register checksum mismatch")
        snapshot["data"] = json.loads(raw)
        if snapshot["data"].get("error") or snapshot["data"].get("exceededTransferLimit"):
            raise ValueError("Incomplete Jardine register evidence")
    a, = _attributes(home["address"])
    block, = home["block"]["data"]["features"]
    b = block["properties"]
    if not (a["ADDRESS_ID"] == 140619 and a["UNIT_TITLE"] == a["DOOR_NO"] == "3" and a["UNITPLAN_NO"] == "402"
            and a["ASSIGNED"] == "ASSIGNED" and a["UNIT_CLASS"] == "A" and a["SUBADDTYPE"] == "Unit"
            and a["BLOCK_KEY"] == b["BLOCK_KEY"] == 12170260047 and a["DIVISION"] == b["DIVISION_NAME"] == "KINGSTON"
            and b["CURRENT_LIFECYCLE_STAGE"] == "REGISTERED" and _attributes(home["unit"]) == []):
        raise ValueError("The Jardine address and parcel captures do not support the recorded identity")
    home["dwelling"] = {"property_type": "unit", "bedrooms": None, "source_url": home["address"]["query_url"],
                        "source": "ACT address record. Bedroom count and the separate unit polygon remain unverified."}
    return home


def _home_for_id(address_id):
    return _jardine_register() if str(address_id) == "140619" else _register().get(str(address_id))


def _refs(*snapshots):
    fields = ("source_id", "query_url", "retrieved_at", "response_sha256", "attribution",
              "terms_url", "licence_url", "licence_metadata_url")
    return [{key: item[key] for key in fields} for item in snapshots]


def _match(home):
    record, = _attributes(home["address"])
    point = buyer_location.address_point(record)
    return {**point, "source_url": home["address"]["query_url"], "source_date": home["address"]["retrieved_at"],
            "unit_id": record["UNIT_TITLE"], "property_type": home["dwelling"]["property_type"],
            "bedrooms": home["dwelling"]["bedrooms"], "dwelling_source_url": home["dwelling"]["source_url"],
            "dwelling_source": home["dwelling"]["source"],
            "basis": "Retained ACT Government address point", "attribution": home["address"]["attribution"]}


def examples():
    return {"matches": [_match(home) for home in _register().values()], "truncated": False}


def lookup_addresses(street, suburb):
    """Use local data only for an exact unit, street and locality match."""
    street = " ".join(street.strip().upper().split())
    street = re.sub(r"^UNIT\s+(\d+[A-Z]?)\s*,?\s+(?=\d)", r"\1/", street)
    street = re.sub(r"^UNIT\s+", "", street)
    street = re.sub(r"\s*/\s*", "/", street)
    words = street.split()
    if words:
        words[-1] = buyer_location.STREET_TYPES.get(words[-1], words[-1])
    if " ".join(words) == "3/9 JARDINE STREET" and suburb.strip().upper() == "KINGSTON":
        return {"matches": [{**_match(_jardine_register()), "retained_address_match": True}], "truncated": False}
    for home in _register().values():
        a, = _attributes(home["address"])
        full = f"{a['DOOR_NO']}/{a['STREET_NUMBER']} {a['STREET_NAME']} {a['STREET_TYPE']}"
        if " ".join(words) == full and suburb.strip().upper() == a["DIVISION"]:
            return {"matches": [_match(home)], "truncated": False}
    return buyer_location.lookup_addresses(street, suburb)


def retained_property(address_id):
    home = _home_for_id(address_id)
    if home is None:
        return None
    a, = _attributes(home["address"])
    block, = home["block"]["data"]["features"]
    b = block["properties"]
    latest = max(home[key]["retrieved_at"] for key in _IDENTITY_KEYS)
    extra = ({"state": "ACT", "unit_polygon_status": "No separate unit polygon matched the retained register query"}
             if str(address_id) == "140619" else {})
    return {**_match(home), **extra, "jurisdiction": "ACT", "unit_required": True,
            "ownership_form": "unit_title", "units_plan_no": a["UNITPLAN_NO"], "unit_class": a["UNIT_CLASS"],
            "identity_confirmed": True, "block_key": b["BLOCK_KEY"], "block": b["BLOCK_NUMBER"],
            "section": b["SECTION_NUMBER"], "division": b["DIVISION_NAME"],
            "parcel_geometry": deepcopy(block["geometry"]), "crs": "EPSG:7855",
            "retrieved_at": latest, "source_ids": list(_IDENTITY_SOURCES),
            "public_sources": _refs(*(home[key] for key in _IDENTITY_KEYS))}


def _instant(value):
    moment = datetime.fromisoformat(value)
    if len(value) == 10:
        return moment.replace(tzinfo=timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("A timezone-aware cutoff is required")
    return moment


def _confirmed_home(case):
    prop = case.get("property") or {}
    aid = str(prop.get("address_id"))
    expected = retained_property(aid)
    if not expected or prop.get("ambiguous") or prop.get("identity_confirmed") is not True:
        return None
    if prop.get("state") is not None and buyer_location.locality_key(prop["state"]) not in (
            "ACT", "AUSTRALIANCAPITALTERRITORY"):
        return None
    canonical_ids = {f"act-address-{aid}",
                     f"act:block-{expected['block_key']}:unit-{expected['unit_id']}"}
    if case.get("property_id") not in canonical_ids:
        return None
    required = ("unit_id", "block_key", "jurisdiction")
    optional = ("units_plan_no", "unit_class", "suburb", "division", "block", "section", "ownership_form",
                "label", "crs")
    if any(str(prop.get(k, "")).casefold() != str(expected[k]).casefold()
           for k in (*required, *(k for k in optional if k in prop))):
        return None
    if prop.get("property_type") not in ("unit", "townhouse") or prop.get("unit_required") is False:
        return None
    if "latitude" in prop or "longitude" in prop:
        point = buyer_location.coordinates(prop.get("latitude"), prop.get("longitude"))
        if not point or any(abs(x-y) > 0.000001 for x, y in zip(point, (expected["latitude"], expected["longitude"]))):
            return None
    if "parcel_geometry" in prop and (prop.get("crs") != expected["crs"]
            or not shape(prop["parcel_geometry"]).equals(shape(expected["parcel_geometry"]))):
        return None
    if _instant(case["as_of"]) < _instant(expected["retrieved_at"]):
        return None
    # Verify the actual register point against the dated ACT division polygons.
    if buyer_location.location_for_case({**case, "property": expected}).get("issue"):
        return None
    return _home_for_id(aid)


def retained_location_evidence(case):
    home = _confirmed_home(case)
    if home is None or "address_zone" not in home:
        return []
    cutoff = _instant(case["as_of"])
    rows = []

    def add(keys, **signal):
        snapshots = [home[key] for key in keys]
        known = max(home[k]["retrieved_at"] for k in (*keys, *_IDENTITY_KEYS))
        if cutoff >= _instant(known):
            refs = _refs(*snapshots)
            rows.append({**signal, "source_url": refs[0]["query_url"], "as_of": known, "retrieved_at": known,
                         "source_ids": sorted(set(_IDENTITY_SOURCES) | {r["source_id"] for r in refs}),
                         "attribution": refs[0]["attribution"], "licence_url": refs[0]["licence_url"],
                         "public_sources": refs})

    addr_zones = _attributes(home["address_zone"])
    inner_zones = _attributes(home["block_interior_zone"])
    if len(addr_zones) == 1 and addr_zones == inner_zones:
        zone = addr_zones[0]
        code, label = zone["LAND_USE_ZONE_CODE_ID"], zone["LAND_USE_POLICY_DESC"].title()
        a, = _attributes(home["address"])
        block, = home["block"]["data"]["features"]
        distance = shape(block["geometry"]).distance(Point(*_MGA.transform(float(a["LONG"]), float(a["LAT"]))))
        point_note = f" The address point lies about {round(distance)} m outside the mapped parent block." if distance > 1 else ""
        add(("address_zone", "block_interior_zone"), kind="zoning", status="mapped", zone_code=code,
            zone_description=label, title=f"{code} {label}", scope="address point and parent-block interior sample",
            detail=f"The gazetted Territory Plan maps the address point and a point inside the registered parent block to {code} {label}.{point_note} Check parcel-wide overlays and permitted uses before relying on development potential.")

    small, large = (home[f"fire_{radius}"]["data"]["objectIds"] for radius in (200, 500))
    if isinstance(small, list) and isinstance(large, list) and set(small) <= set(large):
        near = bool(large)
        count_200, count_500 = len(set(small)), len(set(large))
        detail = (f"The ACT 2026 designation has {count_500} mapped features within 500 m of the address point and {count_200} within 200 m. "
                  "Ask the insurer to assess the specific dwelling and obtain a written quote." if near else
                  "The ACT 2026 designation search returned no mapped features within 500 m of the address point. Obtain a dwelling-specific insurance quote.")
        add(("fire_500", "fire_200"), kind="bushfire_proximity",
            status="nearby_designation" if near else "none_in_search", nearby_designation=near,
            count_within_200m=count_200, count_within_500m=count_500, radius_m=500,
            title="Mapped bushfire-prone area within 500 m" if near else "No mapped bushfire-prone area within 500 m",
            scope="500 m from the registered address point", detail=detail +
            " The search measures proximity only. Building exposure, premiums and policy terms remain unknown.")
    return rows


def public_evidence(case):
    home = _confirmed_home(case)
    if home is None:
        return []
    prop = case["property"]
    rows = []
    if str(prop["address_id"]) == "793201":
        for row in build_kingston_public_evidence(case):
            if row["check_id"] == "S002":
                continue
            rows.append(row)
    for key in ("address", "unit"):
        snapshot = home[key]
        if not _attributes(snapshot):
            continue
        source = snapshot["source_id"]
        sid = snapshot["response_sha256"]
        identity = f"{case['property_id']}-{source}-{sid}"
        oid = hashlib.sha256(identity.encode()).hexdigest()[:24]
        rows.append({"observation_id": f"preoffer-S002-{oid}", "check_id": "S002",
                     "property_id": case["property_id"], "source_id": source, "snapshot_id": "sha256:" + sid,
                     "published_at": max(home[k]["retrieved_at"] for k in _IDENTITY_KEYS),
                     "knowledge_date_basis": "Register capture", "visibility_scope": "public",
                     "owner_tenant_id": None, "case_scope_id": None, "evidence_basis": "official_record",
                     "source_ids": list(_IDENTITY_SOURCES), "confidence": "Medium",
                     "rights": dict.fromkeys(("process", "retain_raw", "display_raw", "display_derived"), True),
                     "quality": {"retrieval_status": "SUCCESS", "coverage_status": "COVERED",
                                 "identity_match": True, "complete": True, "current": True},
                     "public_sources": _refs(snapshot), "payload": {"kind": "unit_register",
                                                                      "records": deepcopy(_attributes(snapshot))}})
    return rows
