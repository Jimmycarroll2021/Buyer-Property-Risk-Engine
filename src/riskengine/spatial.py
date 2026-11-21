"""Coverage-first parcel and footprint screening in a declared metric CRS.

Geometry is evidence about a mapped extent, never a prediction of loss. Invalid
geometries are rejected rather than silently repaired or reduced to centroids.
"""
from __future__ import annotations

import math
from typing import Any

from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError, ProjError
from shapely.geometry import GeometryCollection, shape
from shapely.errors import ShapelyError
from shapely.ops import transform
from shapely.validation import explain_validity

AREA_EPSILON_M2 = 1e-8


class SpatialInputError(ValueError):
    pass


def _number(value: Any, name: str, minimum: float | None = 0) -> float:
    if isinstance(value, bool) or value is None:
        raise SpatialInputError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise SpatialInputError(f"{name} must be a finite number") from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise SpatialInputError(f"{name} must be finite and at least {minimum}")
    return result


def _geometry(value: Any, name: str, *, empty_allowed: bool = False):
    if value is None:
        raise SpatialInputError(f"{name} is required")
    try:
        geom = shape(value)
    except (ValueError, TypeError, KeyError, IndexError, ShapelyError) as exc:
        raise SpatialInputError(f"{name} is not a supported GeoJSON geometry") from exc
    if geom.is_empty:
        if empty_allowed:
            return GeometryCollection()
        raise SpatialInputError(f"{name} is empty")
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise SpatialInputError(f"{name} must be a parcel or footprint polygon, not a point or line")
    if not geom.is_valid:
        raise SpatialInputError(f"{name} is invalid: {explain_validity(geom)}")
    if any(not math.isfinite(n) for n in geom.bounds):
        raise SpatialInputError(f"{name} has non-finite coordinates")
    return geom


def _crs(value: Any, name: str) -> CRS:
    if value is None:
        raise SpatialInputError(f"{name} is required")
    try:
        return CRS.from_user_input(value)
    except (CRSError, ValueError, TypeError) as exc:
        raise SpatialInputError(f"{name} is not a recognised CRS") from exc


def _project(geom, source: CRS, target: CRS):
    if source == target or geom.is_empty:
        return geom
    if source.is_geographic and not (-180 <= geom.bounds[0] <= 180 and
            -180 <= geom.bounds[2] <= 180 and -90 <= geom.bounds[1] <= 90 and -90 <= geom.bounds[3] <= 90):
        raise SpatialInputError("Geographic coordinates are outside longitude/latitude bounds")
    try:
        converted = transform(Transformer.from_crs(source, target, always_xy=True).transform, geom)
    except (ProjError, ValueError, TypeError) as exc:
        raise SpatialInputError("CRS transformation failed") from exc
    if not converted.is_valid or any(not math.isfinite(n) for n in converted.bounds):
        raise SpatialInputError("CRS transformation returned invalid or non-finite geometry")
    return converted


def assess_spatial(payload: dict, *, coverage_status: str = "UNKNOWN") -> dict:
    """Return the mapped relation, withholding conclusions without full coverage.

    ``coverage_status`` is supplied from the independently verified source
    coverage contract; an empty hazard extent never proves coverage. A separate
    coverage polygon can narrow but cannot replace that source contract.
    """
    base = {"state": "NOT_ASSESSED", "relation": None, "overlap_area_m2": None,
            "subject_scope": payload.get("subject_scope", "parcel"),
            "method": "polygon_overlay_with_explicit_coverage_and_uncertainty"}
    if coverage_status != "COVERED":
        return {**base, "reason": "OUTSIDE_COVERAGE" if coverage_status == "OUTSIDE_COVERAGE" else "COVERAGE_UNKNOWN"}
    try:
        subject = _geometry(payload.get("subject_geometry"), "subject_geometry")
        hazard = _geometry(payload.get("hazard_geometry"), "hazard_geometry", empty_allowed=True)
        source = _crs(payload.get("crs"), "crs")
        hazard_crs = _crs(payload.get("hazard_crs", payload.get("crs")), "hazard_crs")
        if payload.get("metric_crs") is not None:
            target = _crs(payload["metric_crs"], "metric_crs")
        elif source.is_projected and all(a.unit_name in ("metre", "meter") for a in source.axis_info[:2]):
            target = source
        else:
            raise SpatialInputError("metric_crs is required when the subject CRS is not projected in metres")
        if not target.is_projected or len(target.axis_info) < 2 or any(a.unit_name not in ("metre", "meter") for a in target.axis_info[:2]):
            raise SpatialInputError("metric_crs must be a projected coordinate system in metres")
        subject = _project(subject, source, target)
        hazard = _project(hazard, hazard_crs, target)
        uncertainty = _number(payload.get("positional_uncertainty_m"), "positional_uncertainty_m")
        base.update(crs=source.to_string(), metric_crs=target.to_string(), hazard_crs=hazard_crs.to_string(),
                    positional_uncertainty_m=uncertainty, subject_area_m2=round(subject.area, 6))
        if subject.area <= AREA_EPSILON_M2:
            raise SpatialInputError("Subject polygon has no positive metric area")
        if payload.get("coverage_geometry") is not None:
            coverage = _geometry(payload["coverage_geometry"], "coverage_geometry")
            coverage_crs = _crs(payload.get("coverage_crs", payload.get("crs")), "coverage_crs")
            coverage = _project(coverage, coverage_crs, target)
            if not coverage.covers(subject):
                return {**base, "reason": "OUTSIDE_COVERAGE", "relation": "OUTSIDE_COVERAGE",
                        "coverage_scope": "full_subject_not_covered"}
        area = 0 if hazard.is_empty else subject.intersection(hazard).area
        base.update(overlap_area_m2=round(area, 6), overlap_fraction=round(area/subject.area, 8))
        if hazard.is_empty:
            return {**base, "state": "ASSESSED", "relation": "NO_OVERLAP", "reason": None,
                    "distance_m": None, "scope": "No mapped extent in verified complete source coverage"}
        if area > AREA_EPSILON_M2:
            # Robust overlap requires some positive area to survive moving the
            # mapped hazard boundary inward by the declared combined tolerance.
            robust = uncertainty == 0 or subject.intersection(hazard.buffer(-uncertainty)).area > AREA_EPSILON_M2
            if not robust:
                return {**base, "relation": "BOUNDARY_UNCERTAIN", "reason": "POSITIONAL_UNCERTAINTY",
                        "nominal_relation": "POSITIVE_OVERLAP"}
            return {**base, "state": "ASSESSED", "relation": "POSITIVE_OVERLAP", "reason": None,
                    "distance_m": 0.0, "scope": "Mapped extent overlap only; no depth, frequency, damage or loss conclusion"}
        if subject.touches(hazard) or subject.intersects(hazard):
            return {**base, "relation": "BOUNDARY_TOUCH", "reason": "BOUNDARY_AMBIGUITY", "distance_m": 0.0}
        distance = subject.distance(hazard)
        if distance <= uncertainty:
            return {**base, "relation": "BOUNDARY_UNCERTAIN", "reason": "POSITIONAL_UNCERTAINTY",
                    "distance_m": round(distance, 6), "nominal_relation": "NO_OVERLAP"}
        return {**base, "state": "ASSESSED", "relation": "NO_OVERLAP", "reason": None,
                "distance_m": round(distance, 6), "scope": "No overlap for this mapped mechanism and source version"}
    except (SpatialInputError, ValueError, TypeError, OverflowError, ShapelyError) as exc:
        return {**base, "reason": "GEOMETRY_OR_CRS_UNRESOLVED", "detail": str(exc)}


def vertical_clearance(floor_height: Any, flood_height: Any, *, floor_datum: str | None,
                       flood_datum: str | None, unit: str = "m") -> dict:
    """Explicit datum gate; this helper performs no vertical-datum conversion."""
    if not floor_datum or not flood_datum or floor_datum != flood_datum:
        return {"state": "NOT_ASSESSED", "clearance_m": None, "reason": "VERTICAL_DATUM_UNRESOLVED"}
    if unit != "m":
        return {"state": "NOT_ASSESSED", "clearance_m": None, "reason": "UNIT_UNRESOLVED"}
    try:
        floor = _number(floor_height, "floor_height", minimum=None)
        flood = _number(flood_height, "flood_height", minimum=None)
        return {"state": "ASSESSED", "clearance_m": round(floor-flood, 6),
                "datum": floor_datum, "scope": "Difference between supplied heights for the stated event and datum"}
    except SpatialInputError as exc:
        return {"state": "NOT_ASSESSED", "clearance_m": None, "reason": "INVALID_HEIGHT", "detail": str(exc)}
