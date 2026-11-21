"""Buyer-facing suburb context from dated ACT Policing and ABS publications."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path

from .paths import project_root


def _as_utc(value: str | date | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    elif isinstance(value, str) and len(value) == 10:
        return datetime.combine(date.fromisoformat(value), time.min, tzinfo=timezone.utc)
    else:
        parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("as_of timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def crime_signals(suburb: str, as_of: str | date | datetime) -> list[dict]:
    """Look up an ACT suburb. Callers establish the property's ACT jurisdiction."""
    cutoff = _as_utc(as_of)
    config = project_root() / "config"
    crime = _read(config / "nearby_crime.json")
    source = crime["source_url"]
    unavailable = {
        "title": "Suburb crime figures unavailable",
        "source_url": source,
        "as_of": None,
        "status": "unavailable",
    }
    if cutoff.timestamp() < crime["published_unix_seconds"]:
        return [{**unavailable, "detail": "No ACT Policing extract is available for this assessment date."}]

    key = " ".join((suburb or "").strip().upper().replace("\u2019", "'").split())
    area = crime["areas"].get(key)
    if area is None:
        return [{**unavailable, "detail": "The assessed location has no matching suburb in this ACT Policing extract."}]

    place = key.title()
    last_day = crime["period_ends"][-1]
    burglary_before, burglary = area["Burglary dwellings"]
    theft_before, theft = area["Motor vehicle theft"]
    counts = {
        "title": f"Reported property offences in {place}",
        "detail": (
            f"ACT Policing recorded {burglary} dwelling "
            f"{'burglary' if burglary == 1 else 'burglaries'} in July 2024 to June 2025, "
            f"compared with {burglary_before} in July 2023 to June 2024. Reported motor vehicle "
            f"thefts numbered {theft} and {theft_before} over the same periods. "
            "Later quarters are outside this extract."
        ),
        "source_url": source,
        "as_of": last_day,
        "status": "available",
        "dwelling_burglaries": {"previous_year": burglary_before, "reporting_year": burglary},
        "motor_vehicle_thefts": {"previous_year": theft_before, "reporting_year": theft},
        "period_ends": crime["period_ends"],
        "snapshot_sha256": crime["asset_sha256"],
        "published_at": crime["published_at"],
        "attribution": crime["attribution"],
    }

    population = _read(config / "nearby_crime_population.json")
    rate = {
        "title": f"Property offence rates in {place}",
        "source_url": population["source_url"],
        "as_of": last_day,
        "status": "unavailable",
    }
    people = population["areas"].get(key)
    if cutoff < _as_utc(population["release_at"]):
        rate["detail"] = "A matching population estimate was unavailable for this period at the assessment date."
    elif people is None:
        rate["detail"] = "A population estimate with matching suburb boundaries is unavailable. A per-resident rate cannot be calculated."
    else:
        average = (people["erp_2024"] + people["erp_2025"]) / 2
        if average <= 0:
            rate["detail"] = "The estimated resident population was zero. A per-resident rate cannot be calculated."
        else:
            rate["status"] = "available"
            rate.update(population_2024=people["erp_2024"], population_2025=people["erp_2025"],
                        population_published_at=population["release_at"], attribution=population["attribution"],
                        numerator_source_url=source, population_method=population["method"])
            rate["detail"] = (
                f"From July 2024 to June 2025, {place} recorded {1000 * burglary / average:.1f} "
                f"dwelling burglaries and {1000 * theft / average:.1f} motor vehicle thefts per "
                f"1,000 residents. The denominator averages the ABS June 2024 and June 2025 "
                f"resident estimates ({people['erp_2024']:,} and {people['erp_2025']:,}). "
                "Offences include those affecting visitors. An individual home's chance of burglary cannot be inferred."
            )
    return [counts, rate]
