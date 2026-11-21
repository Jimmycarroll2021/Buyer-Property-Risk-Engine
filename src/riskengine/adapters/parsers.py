"""Pure parsers. Preserve meaning, units, absent values and source locations."""
from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import io
import json
import math
import re
import zipfile

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from .common import SourceError


def esri_to_geojson(geometry):
    """Convert ESRI geometry shape while retaining CRS separately.

    Ring nesting determines shells/holes, so reversed ring orientation does not
    erase holes. Invalid/ambiguous rings are rejected, not silently repaired.
    """
    if geometry is None:
        return None
    if "x" in geometry and "y" in geometry:
        return {"type": "Point", "coordinates": [geometry["x"], geometry["y"]]}
    if "points" in geometry:
        return {"type": "MultiPoint", "coordinates": geometry["points"]}
    if "paths" in geometry:
        paths = geometry["paths"]
        return {"type": "LineString", "coordinates": paths[0]} if len(paths) == 1 else {"type": "MultiLineString", "coordinates": paths}
    if all(k in geometry for k in ("xmin", "ymin", "xmax", "ymax")):
        x0, y0, x1, y1 = [geometry[k] for k in ("xmin", "ymin", "xmax", "ymax")]
        return {"type": "Polygon", "coordinates": [[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]]}
    if "rings" not in geometry:
        raise SourceError("UNSUPPORTED_GEOMETRY", "Unsupported ESRI geometry representation")
    from shapely.geometry import Polygon, MultiPolygon
    rings = geometry["rings"]
    if not rings:
        raise SourceError("INVALID_GEOMETRY", "Polygon has no rings")
    polys = [Polygon(r) for r in rings]
    if any(not p.is_valid or p.is_empty or p.area == 0 for p in polys):
        raise SourceError("INVALID_GEOMETRY", "Polygon contains an invalid ring")
    parents = []
    for i,p in enumerate(polys):
        containing = [j for j,q in enumerate(polys) if j != i and q.area > p.area and q.covers(p)]
        parents.append(min(containing, key=lambda j: polys[j].area) if containing else None)
    def depth(i):
        n=0
        while parents[i] is not None:
            n+=1;i=parents[i]
            if n>len(rings):raise SourceError("INVALID_GEOMETRY", "Polygon ring cycle")
        return n
    output=[]
    for i in range(len(rings)):
        if depth(i)%2==0:
            holes=[rings[j] for j in range(len(rings)) if parents[j]==i and depth(j)%2==1]
            p=Polygon(rings[i],holes)
            if not p.is_valid:
                raise SourceError("INVALID_GEOMETRY", "Polygon shell and holes are invalid")
            output.append([rings[i],*holes])
    if len(output)==1:return {"type":"Polygon","coordinates":output[0]}
    combined = MultiPolygon([Polygon(r[0], r[1:]) for r in output])
    if not combined.is_valid:
        raise SourceError("INVALID_GEOMETRY", "Polygon components overlap or have ambiguous boundaries")
    return {"type":"MultiPolygon","coordinates":output}


def _date(text):
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%b-%Y", "%Y-%m"):
        try:return datetime.strptime(text.strip(),fmt).date().isoformat()
        except (ValueError,TypeError):continue
    return None


def _decimal(value):
    try:
        d=Decimal(str(value))
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):return None


def parse_rba_csv(body, *, series_ids=None):
    rows=list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
    metadata={r[0].strip():r for r in rows if r and r[0].strip() in {"Series ID","Title","Description","Frequency","Type","Units","Source","Publication date"}}
    if "Series ID" not in metadata:
        raise SourceError("SCHEMA_CHANGED", "RBA CSV has no Series ID metadata row")
    ids=metadata["Series ID"]
    selected=list(series_ids or (["FIRMMCRTD"] if "FIRMMCRTD" in ids else ids[1:]))
    if any(s not in ids for s in selected):
        raise SourceError("SCHEMA_CHANGED", "Requested RBA series identifier is absent")
    def meta(k,i):
        row=metadata.get(k,[])
        return row[i] if len(row)>i else None
    out=[]
    for rn,row in enumerate(rows,1):
        if not row:continue
        period=_date(row[0])
        if not period:continue
        for sid in selected:
            i=ids.index(sid);raw=row[i].strip() if len(row)>i else ""
            value=_decimal(raw) if raw else None
            units=meta("Units",i)
            item={"series_id":sid,"period":period,"value":str(value) if value is not None else None,
                  "raw_value":raw,"unit":units,"frequency":meta("Frequency",i),"title":meta("Title",i),
                  "publication_date":_date(meta("Publication date",i) or ""),"source_row":rn,
                  "observation_status":"OBSERVED" if value is not None else ("MISSING" if not raw else "NON_NUMERIC")}
            if units and units.lower() in {"per cent","percent","%"}:
                item["value_decimal"]=str(value/100) if value is not None else None
            out.append(item)
    out.sort(key=lambda x:(x["period"],x["series_id"]),reverse=True)
    return out,{"format":"RBA metadata CSV","series_ids":selected,"metadata":metadata,"record_order":"newest period first","numeric_encoding":"decimal string"}


def parse_crime_xlsx(body, *, area=None, max_expanded_bytes=160_000_000):
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            if sum(x.file_size for x in archive.infolist())>max_expanded_bytes:
                raise SourceError("EXPANSION_LIMIT","Workbook expanded size exceeds limit")
        workbook=load_workbook(io.BytesIO(body),read_only=True,data_only=True)
    except SourceError:raise
    except Exception as exc:raise SourceError("INVALID_WORKBOOK","Could not read the crime workbook") from exc
    out=[];periods=set();categories=set()
    try:
        for sheet in workbook:
            category=None;headers=None;source_note=None
            for rn,row in enumerate(sheet.iter_rows(values_only=True),1):
                if not row:continue
                first=row[0]
                if first is not None and all(v is None for v in row[1:]):
                    category=str(first).strip()
                    if "as at" in category.lower():source_note=category
                if len(row)>1 and isinstance(row[1],str) and re.match(r"^\d{4}\s+Q[1-4]",row[1]):
                    headers=list(row);continue
                if not headers or not first or not category:continue
                name=str(first).strip()
                if area and name.casefold()!=str(area).strip().casefold():continue
                # Category lines, notes and totals are not suburb observations.
                if name==category or name.lower().startswith(("total","notes:","source:")) or not any(v is not None for v in row[1:]):continue
                for col,h in enumerate(headers[1:],1):
                    if not isinstance(h,str):continue
                    m=re.match(r"^(\d{4})\s+Q([1-4])",h)
                    if not m:continue
                    raw=row[col] if col<len(row) else None
                    numeric=isinstance(raw,(int,float)) and not isinstance(raw,bool) and math.isfinite(raw) and raw>=0 and float(raw).is_integer()
                    count=int(raw) if numeric else None
                    period=f"{m.group(1)}-Q{m.group(2)}"
                    out.append({"area_name":name,"area_type":"publisher reporting area","category":category,
                                "category_family":"infringement_activity" if category.startswith(("TINs","CINs")) else "reported_offence",
                                "period":period,"count":count,"raw_value":raw,
                                "observation_status":"OBSERVED" if numeric else ("MISSING" if raw is None else "NON_NUMERIC_OR_SUPPRESSED"),
                                "source_sheet":sheet.title,"source_cell":f"{get_column_letter(col+1)}{rn}","source_note":source_note})
                    periods.add(period);categories.add(category)
    finally:workbook.close()
    if not out:raise SourceError("SCHEMA_CHANGED","No expected area/category/quarter observations found in workbook")
    seen=set()
    for row in out:
        key=(row["area_name"],row["category"],row["period"])
        if key in seen:raise SourceError("DUPLICATE_OBSERVATION","Duplicate area/category/period in crime workbook requires reconciliation")
        seen.add(key)
    out.sort(key=lambda x:(x["period"],x["area_name"],x["category"]),reverse=True)
    return out,{"format":"ACT quarterly crime workbook","periods":sorted(periods),"categories":sorted(categories),"area_filter":area,"unit":"published count","record_order":"newest quarter first","rates_calculated":False}


def parse_sdmx_csv(body):
    text=body.decode("utf-8-sig")
    reader=csv.DictReader(io.StringIO(text));fields=reader.fieldnames or []
    if "OBS_VALUE" not in fields:
        raise SourceError("SCHEMA_CHANGED","Expected SDMX data CSV with OBS_VALUE; a discovery/dataflow URL is not a data query")
    out=[]
    for rn,row in enumerate(reader,2):
        val=_decimal(row.get("OBS_VALUE"))
        out.append({"dimensions":{k:v for k,v in row.items() if k!="OBS_VALUE"},"value":str(val) if val is not None else None,
                    "raw_value":row.get("OBS_VALUE"),"unit":row.get("UNIT_MEASURE"),"unit_multiplier":row.get("UNIT_MULT"),
                    "period":row.get("TIME_PERIOD"),"source_row":rn,
                    "observation_status":"OBSERVED" if val is not None else "MISSING_OR_NON_NUMERIC"})
    return out,{"format":"SDMX CSV","fields":fields,"units_policy":"UNIT_MEASURE and UNIT_MULT retained; no assumed conversion or sum across dimensions"}


def parse_gtfs_zip(body, *, max_expanded_bytes=160_000_000, max_records=1000):
    try:archive=zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as exc:raise SourceError("INVALID_ZIP","GTFS response is not a ZIP file") from exc
    with archive:
        entries=[i for i in archive.infolist() if not i.is_dir()]
        if len(entries)>200 or sum(i.file_size for i in entries)>max_expanded_bytes:
            raise SourceError("EXPANSION_LIMIT","GTFS ZIP exceeds expanded size or member limit")
        names={}
        for info in entries:
            name=info.filename.replace("\\","/").split("/")[-1]
            if name in names:raise SourceError("DUPLICATE_ZIP_MEMBER","GTFS ZIP contains duplicate table names")
            names[name]=info
        required={"agency.txt","routes.txt","stops.txt","trips.txt","stop_times.txt"}
        missing=required-set(names)
        if missing or not ({"calendar.txt","calendar_dates.txt"}&set(names)):
            raise SourceError("GTFS_REQUIRED_FILES","GTFS schedule lacks required files or service calendar")
        out=[];tables={};total=0
        for name in sorted(names):
            if not name.endswith(".txt"):continue
            with archive.open(names[name]) as raw:
                reader=csv.DictReader(io.TextIOWrapper(raw,encoding="utf-8-sig",newline=""))
                count=0
                for rn,row in enumerate(reader,2):
                    count+=1;total+=1
                    if len(out)<max_records:out.append({"table":name,"source_row":rn,"attributes":row})
                tables[name]={"fields":reader.fieldnames,"rows":count}
    return out,{"format":"GTFS schedule ZIP","tables":tables,"total_rows":total,"record_cap_reached":total>len(out),"service_timezone_policy":"Retain agency_timezone and service-day times; hours above24 are valid"}

