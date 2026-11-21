"""Offline, point-level ACT Territory Plan zoning from a bounded government extract."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, time, timezone

from shapely.geometry import Point, shape

from .paths import project_root


_LAYER = (
    "https://services1.arcgis.com/E5n4f1VY84i0xSjy/arcgis/rest/services/"
    "ACTGOV_TP_LAND_USE_ZONE/FeatureServer/1"
)


def _instant(value: str | date) -> datetime:
    if isinstance(value, str):
        value = date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("A timestamp needs a timezone")
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        # A date-only assessment includes all observations from that UTC day.
        return datetime.combine(value, time.max, tzinfo=timezone.utc)
    raise ValueError("A date or timezone-aware timestamp is required")


def spatial_signals(latitude: float, longitude: float, as_of: str | date) -> list[dict]:
    """Look up a WGS 84 point. Dates select the latest available layer version."""
    signal = {
        "title": "Territory Plan land use zone",
        "source_url": _LAYER,
        "as_of": None,
        "status": "unknown",
    }
    try:
        if isinstance(latitude, bool) or isinstance(longitude, bool):
            raise ValueError
        lat, lon = float(latitude), float(longitude)
        if not (math.isfinite(lat) and -90 <= lat <= 90 and math.isfinite(lon) and -180 <= lon <= 180):
            raise ValueError
        assessment_time = _instant(as_of)
    except (TypeError, ValueError, OverflowError):
        return [{**signal, "detail": "A valid WGS 84 latitude, longitude and assessment date are required."}]

    config = project_root() / "config"
    try:
        metadata = json.loads((config / "nearby_spatial_metadata.json").read_text(encoding="utf-8"))
        version = metadata["layer_data_last_edit_utc"]
        if assessment_time < _instant(version):
            return [{**signal, "detail": "The saved zoning layer postdates this assessment. Historical zoning is unknown."}]
        if assessment_time < _instant(metadata["retrieved_at_utc"]):
            return [{**signal, "detail": "The zoning snapshot was captured after this assessment date. Historical zoning is unknown."}]

        signal.update(
            as_of=version,
            retrieved_at=metadata["retrieved_at_utc"],
            snapshot_sha256=metadata["snapshot_sha256"],
            attribution=metadata["attribution"],
            licence_url=metadata["licence_url"],
        )
        west, south, east, north = metadata["bbox"]
        if not (west <= lon <= east and south <= lat <= north):
            return [{
                **signal,
                "status": "outside_coverage",
                "detail": "The point lies outside the saved Kingston and inner south zoning extract. Zoning is unknown.",
            }]

        raw = (config / "nearby_spatial_zones.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != metadata["snapshot_sha256"]:
            raise ValueError("Zoning snapshot checksum mismatch")
        features = json.loads(raw)["features"]
        if len(features) != metadata["feature_count"]:
            raise ValueError("Zoning snapshot count mismatch")
        point = Point(lon, lat)
        zones = set()
        for feature in features:
            if shape(feature["geometry"]).covers(point):
                fields = feature["properties"]
                zones.add((fields["LAND_USE_ZONE_CODE_ID"], fields["LAND_USE_POLICY_DESC"].title()))
    except (OSError, KeyError, TypeError, ValueError):
        return [{**signal, "detail": "The local zoning evidence could not be verified. Zoning is unknown."}]

    if not zones:
        return [{**signal, "detail": "No gazetted zone polygon covers this point in the saved extract. Check the Territory Plan map for this location."}]

    label = ", ".join(f"{code} {description}" for code, description in sorted(zones))
    detail = (
        f"The ACT Government map places the selected point in {label}. "
        if len(zones) == 1 else
        f"Multiple mapped zones touch or cover this point ({label}). Check the parcel boundaries. "
    )
    return [{
        **signal,
        "status": "mapped" if len(zones) == 1 else "multiple_zones",
        "detail": (
            detail + f"Layer updated {version[:10]}, snapshot retrieved {signal['retrieved_at'][:10]}. "
            "Confirm the full block, overlays and permitted uses against the Territory Plan."
        ),
        "zones": [{"code": code, "description": desc} for code, desc in sorted(zones)],
    }]
