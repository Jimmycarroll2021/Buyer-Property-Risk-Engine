"""Local proximity checks against a dated, partial ACT planning snapshot."""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform

from .paths import project_root


_MGA55 = Transformer.from_crs("EPSG:4326", "EPSG:7855", always_xy=True)


@lru_cache(maxsize=4)
def _snapshot(config_dir: Path):
    config = json.loads((config_dir / "nearby_planning.json").read_text("utf-8"))
    data_dir = config_dir / "nearby_planning_data"
    layers = {}
    for name in ("da", "stage_2a"):
        path = data_dir / config[name]["file"]
        features = json.loads(path.read_bytes())["features"]
        layers[name] = [
            (feature["properties"], transform(_MGA55.transform, shape(feature["geometry"])))
            for feature in features
        ]
    layers["stage_2b"] = [
        (location, Point(*_MGA55.transform(*location["coordinates"])))
        for location in config["stage_2b"]["locations"]
    ]
    return config, layers


def _cutoff(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(value).date()


def planning_signals(latitude: float, longitude: float, as_of: date | str) -> list[dict]:
    """Return selected nearby records known by the cutoff, nearest first.

    An empty result means no matching evidence in this snapshot. The caller
    must identify the limited coverage. All spatial checks run offline.
    """
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return []
    try:
        lat, lon = float(latitude), float(longitude)
        cutoff = _cutoff(as_of).isoformat()
    except (ValueError, TypeError, OverflowError):
        return []
    # The whole snapshot and both screening radii fit well inside this box.
    if not (-36 <= lat <= -35 and 148.5 <= lon <= 149.5):
        return []

    config, layers = _snapshot(project_root() / "config")
    point = Point(*_MGA55.transform(lon, lat))
    signals = []
    for name, features in layers.items():
        source = config[name]
        if cutoff < max(source["as_of"], source["geometry_as_of"]):
            continue
        nearby = sorted(
            ((point.distance(geometry), props) for props, geometry in features),
            key=lambda item: item[0],
        )
        for distance, props in nearby:
            if distance > (1000 if name == "da" else 2000):
                break
            metres = round(distance)
            row = {
                "as_of": source["as_of"],
                "source_url": source["source_url"],
                "attribution": source["attribution"],
                "terms_url": source["terms_url"],
                "coverage": config["coverage"],
                "geometry_as_of": source["geometry_as_of"],
                "distance_method": source["distance_method"],
            }
            if name == "da":
                status = props["status"]
                title = f"{props['title']} | DA {props['number']}"
                detail = (
                    f"{props['address']}. {props['summary']} Lodged {props['lodged']}. "
                    f"The original application was listed as {status.lower()} on {source['as_of']}. "
                    f"The address point is approximately {metres:,} m from the mapped application land. "
                    "Check the DA record for amendments or a decision."
                )
                row["source_url"] += props["number"]
                row["geometry_source_url"] = source["spatial_source"]
                row["licence_url"] = source["licence_url"]
            elif name == "stage_2a":
                status = "Under construction"
                title = f"Light rail Stage 2A | {props['StopName']}"
                detail = (
                    f"The ACT Government reported this stop under construction on {source['as_of']}. "
                    f"The mapped stop site is about {metres:,} m away in a straight line. "
                    "Passenger services were forecast for 2028 after testing. Check the project update for changes."
                )
                row["geometry_source_url"] = source["geometry_source"]
            else:
                # The reference junction is a proxy for an indicative location.
                # Round to 50 m, since a metre figure would imply undue precision.
                metres = 50 * math.floor(distance / 50 + 0.5)
                status = "Environmental assessment"
                title = f"Proposed light rail Stage 2B | {props['name']}"
                detail = (
                    f"The address is about {metres:,} m in a straight line from {props['reference']}, "
                    "a reference point near the proposed stop. The exact platform and walking distance may differ. "
                    f"The ACT Government reported that the final environmental impact statement was under "
                    f"consideration on {source['as_of']}. Delivery depends on further approvals."
                )
                row["design_source_url"] = source["design_url"]
                row["geometry_source_url"] = source["geometry_source"]
                row["licence_url"] = source["licence_url"]
            row.update(title=title, detail=detail, status=status, distance_m=metres)
            signals.append((distance, row))
            if name != "da":
                break
    return [row for _, row in sorted(signals, key=lambda item: item[0])]
