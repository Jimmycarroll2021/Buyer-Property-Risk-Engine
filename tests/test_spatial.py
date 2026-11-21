"""Spatial acceptance cases PR-AT-002 and PR-AT-006."""
from shapely.geometry import box, mapping

from riskengine.spatial import assess_spatial, vertical_clearance


def payload(subject=None, hazard=None, uncertainty=0):
    return {"kind":"spatial","subject_geometry":mapping(subject if subject is not None else box(0,0,10,10)),
            "hazard_geometry":mapping(hazard if hazard is not None else box(5,0,15,10)),
            "crs":"EPSG:7855","positional_uncertainty_m":uncertainty,"subject_scope":"parcel"}


def test_pr_at_002_coverage_is_independent_from_empty_hazard():
    p=payload();p["hazard_geometry"]={"type":"GeometryCollection","geometries":[]}
    assert assess_spatial(p)["state"] == "NOT_ASSESSED"
    assert assess_spatial(p,coverage_status="OUTSIDE_COVERAGE")["reason"] == "OUTSIDE_COVERAGE"
    assert assess_spatial(p,coverage_status="COVERED")["relation"] == "NO_OVERLAP"


def test_pr_at_006_overlap_touch_nonoverlap_and_uncertainty():
    positive=assess_spatial(payload(),coverage_status="COVERED")
    assert positive["relation"] == "POSITIVE_OVERLAP" and positive["overlap_area_m2"] == 50
    touch=assess_spatial(payload(hazard=box(10,0,20,10)),coverage_status="COVERED")
    assert touch["relation"] == "BOUNDARY_TOUCH" and touch["state"] == "NOT_ASSESSED"
    clear=assess_spatial(payload(hazard=box(12,0,20,10),uncertainty=1),coverage_status="COVERED")
    assert clear["relation"] == "NO_OVERLAP" and clear["distance_m"] == 2
    uncertain=assess_spatial(payload(hazard=box(10.5,0,20,10),uncertainty=1),coverage_status="COVERED")
    assert uncertain["relation"] == "BOUNDARY_UNCERTAIN"
    sliver=assess_spatial(payload(hazard=box(9.5,0,20,10),uncertainty=1),coverage_status="COVERED")
    assert sliver["relation"] == "BOUNDARY_UNCERTAIN"


def test_pr_at_006_footprint_cannot_be_inferred_from_parcel():
    parcel=assess_spatial(payload(),coverage_status="COVERED")
    footprint=payload(subject=box(0,0,3,3));footprint["subject_scope"]="dwelling_footprint"
    dwelling=assess_spatial(footprint,coverage_status="COVERED")
    assert parcel["relation"] == "POSITIVE_OVERLAP"
    assert dwelling["relation"] == "NO_OVERLAP"
    p=payload();p["subject_geometry"]={"type":"Point","coordinates":[5,5]}
    assert assess_spatial(p,coverage_status="COVERED")["state"] == "NOT_ASSESSED"


def test_pr_at_006_metre_projection_and_declared_units():
    p=payload(subject=box(149.1,-35.3,149.1001,-35.2999),hazard=box(149.2,-35.3,149.2001,-35.2999))
    p["crs"]="EPSG:4326"
    assert assess_spatial(p,coverage_status="COVERED")["state"] == "NOT_ASSESSED"
    p["metric_crs"]="EPSG:7855"
    result=assess_spatial(p,coverage_status="COVERED")
    assert result["state"] == "ASSESSED"
    assert 9000 < result["distance_m"] < 9200


def test_partial_source_coverage_never_clears_whole_parcel():
    p=payload();p["coverage_geometry"]=mapping(box(0,0,5,10))
    assert assess_spatial(p,coverage_status="COVERED")["reason"] == "OUTSIDE_COVERAGE"


def test_invalid_geometry_or_missing_accuracy_fails_closed():
    p=payload();p.pop("positional_uncertainty_m")
    assert assess_spatial(p,coverage_status="COVERED")["state"] == "NOT_ASSESSED"
    p=payload();p["subject_geometry"]={"type":"Polygon","coordinates":[[[0,0],[10,10],[0,10],[10,0],[0,0]]]}
    assert assess_spatial(p,coverage_status="COVERED")["state"] == "NOT_ASSESSED"


def test_pr_at_006_vertical_datum_must_match():
    assert vertical_clearance(600,599,floor_datum="AHD",flood_datum="ELLIPSOID")["state"] == "NOT_ASSESSED"
    assert vertical_clearance(600,599,floor_datum="AHD",flood_datum="AHD")["clearance_m"] == 1
