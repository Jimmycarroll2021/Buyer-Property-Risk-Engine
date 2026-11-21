"""Read-only presentation over one case version and separately sourced location context."""
from shapely.errors import GEOSException
from pyproj.exceptions import ProjError
from .buyer_location import location_for_case
from .nearby_crime import crime_signals
from .nearby_planning import planning_signals
from .nearby_spatial import spatial_signals
from .buyer_finance import finance_signals


def missing(title, detail, as_of):
    return [{"title": title, "detail": detail, "as_of": as_of, "status": "unknown"}]


LOCATION_SOURCES = ("act_addresses", "act_boundary")
PLANNING_SOURCES = ("act_da_active", "act_da_finder", "act_light_rail_stage_2a", "act_light_rail_stage_2b")
ZONING_SOURCES = ("act_tp_zoning",)
CRIME_SOURCES = ("act_crime_statistics", "canberra_crm01", "canberra_dem01")
LOCAL_SOURCES = LOCATION_SOURCES + PLANNING_SOURCES + ZONING_SOURCES + CRIME_SOURCES
SOURCE_ERRORS = (OSError, ValueError, KeyError, TypeError, IndexError, GEOSException, ProjError)


def buyer_context(case, assessment, *, restricted_sources=()):
    as_of = case["as_of"]
    used_sources = set()
    restricted = set(restricted_sources)
    prop = case.get("property") or {}
    fallback_location = {"label": prop.get("label") or case["property_id"], "suburb": None,
                         "latitude": None, "longitude": None, "basis": "Location recorded in this case"}
    if any(prop.get(key) is not None for key in ("address_id", "latitude", "longitude")) and restricted.intersection(LOCATION_SOURCES):
        location = {**fallback_location, "issue": "Location source permissions are restricted."}
    else:
        try:
            location = location_for_case(case)
            if location.get("source_url"):
                used_sources.add("act_addresses")
            if location.get("division_source_url") or location.get("latitude") is not None:
                used_sources.add("act_boundary")
        except SOURCE_ERRORS:
            location = {**fallback_location, "issue": "The saved location evidence could not be read or verified."}

    def source_rows(title, source_ids, provider, *args):
        if restricted.intersection(source_ids):
            return missing(title, "Source permissions restrict this local evidence.", as_of)
        try:
            rows = provider(*args, as_of)
        except SOURCE_ERRORS:
            return missing(title, "The saved source extract could not be read or verified.", as_of)
        used_sources.update(source_ids)
        return rows

    lat, lon, suburb = location["latitude"], location["longitude"], location["suburb"]
    if location.get("issue"):
        reason = location["issue"]
        planning = missing("Planning location unconfirmed", reason, as_of)
        spatial = missing("Land-use location unconfirmed", reason, as_of)
        crime = missing("Crime reporting area unconfirmed", reason, as_of)
    elif lat is None or lon is None:
        planning = missing("Planning location unknown", "Choose an ACT address or supply its coordinates in the case.", as_of)
        spatial = missing("Land-use location unknown", "A street address point is needed to check local land use.", as_of)
        crime = source_rows("Crime figures unknown", CRIME_SOURCES, crime_signals, suburb) if suburb else missing("Suburb unknown", "Supply a suburb to check its reported offences.", as_of)
    else:
        planning = source_rows("Planning evidence unknown", PLANNING_SOURCES, planning_signals, lat, lon)
        spatial = source_rows("Land-use evidence unknown", ZONING_SOURCES, spatial_signals, lat, lon)
        crime = source_rows("Crime figures unknown", CRIME_SOURCES, crime_signals, suburb)
    finance = finance_signals(case, assessment) if assessment else missing(
        "Buyer finance has no current assessment", "Run an assessment for this case version to calculate its buyer scenarios.", as_of)
    return {"case_id": case["case_id"], "case_version": case["case_version"], "as_of": as_of,
            "assessment_id": assessment["assessment_id"] if assessment else None, "location": location,
            "illustrative_finance": bool(case.get("finance_is_illustrative") or case.get("demonstration")),
            "source_ids": sorted(used_sources), "planning": planning, "spatial": spatial, "crime": crime, "finance": finance}
