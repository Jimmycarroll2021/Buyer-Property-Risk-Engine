"""Deterministic source adapters with bounded collection and explicit evidence limits.

Network retrieval is not deterministic. Retained snapshots and pure parsing are.
No successful fetch establishes property coverage, rights or a risk finding.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

from .adapters.common import ADAPTER_VERSION, SENSITIVE, SourceError, Transport, atomic_write, canonical_bytes, digest, safe_url
from .adapters.parsers import esri_to_geojson, parse_crime_xlsx, parse_gtfs_zip, parse_rba_csv, parse_sdmx_csv


def load_registry(path=None):
    if path is None:
        path=os.environ.get("RISK_SOURCES_PATH")
    if path is None:
        candidates=[Path(__file__).resolve().parents[2]/"config/sources.json",Path(__file__).parent/"data/sources.json",Path.cwd()/"config/sources.json"]
        path=next((p for p in candidates if p.is_file()),candidates[0])
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    rows=data.get("sources",[]) if isinstance(data,dict) else data
    if not isinstance(rows,list):raise ValueError("Source registry must contain a sources array")
    ids=[r.get("source_id") for r in rows]
    if any(not i for i in ids) or len(set(ids))!=len(ids):raise ValueError("Source IDs must be present and unique")
    return rows


def _base_url(endpoint):
    p=urlsplit(endpoint)
    path=p.path.rstrip("/")
    if path.endswith("/query"):path=path[:-6]
    return urlunsplit((p.scheme,p.netloc,path,"",""))


def _query_scope(source,bounds):
    p=source.get("parameters",{})
    allowed={"where","bbox","in_sr","out_sr"}
    unknown=set(bounds)-allowed
    if unknown:raise SourceError("INVALID_BOUNDS",f"Unsupported scope fields: {', '.join(sorted(unknown))}")
    scope={"where":bounds.get("where",p.get("where","1=1")),"out_sr":bounds.get("out_sr",p.get("out_sr",4326))}
    if not isinstance(scope["where"],str) or not scope["where"].strip():
        raise SourceError("INVALID_BOUNDS","where must be a non-empty source query string")
    if not isinstance(scope["out_sr"],int) or isinstance(scope["out_sr"],bool) or scope["out_sr"]<=0:
        raise SourceError("INVALID_BOUNDS","out_sr must be a positive integer spatial-reference identifier")
    if "in_sr" in bounds and "bbox" not in bounds:
        raise SourceError("INVALID_BOUNDS","in_sr requires a bbox")
    if "bbox" in bounds:
        box=bounds["bbox"]
        if not isinstance(box,list) or len(box)!=4 or any(not isinstance(x,(int,float)) or isinstance(x,bool) for x in box) or box[0]>=box[2] or box[1]>=box[3]:
            raise SourceError("INVALID_BOUNDS","bbox must be [xmin,ymin,xmax,ymax] with ordered finite coordinates")
        if any(not __import__('math').isfinite(x) for x in box):raise SourceError("INVALID_BOUNDS","bbox coordinates must be finite")
        scope.update(bbox=box,in_sr=bounds.get("in_sr",4326))
        if not isinstance(scope["in_sr"],int) or isinstance(scope["in_sr"],bool) or scope["in_sr"]<=0:
            raise SourceError("INVALID_BOUNDS","in_sr must be a positive integer spatial-reference identifier")
    return scope


def _arcgis(source,transport,bounds,max_records):
    scope=_query_scope(source,bounds)
    endpoint=_base_url(source["endpoint"])
    if not re.search(r"/(?:FeatureServer|MapServer)/\d+$",endpoint,re.I):
        raise SourceError("LAYER_REQUIRED","ArcGIS collection requires an exact numbered layer, not a service directory")
    metadata=transport.json(endpoint,params={"f":"json"},kind="layer_metadata")
    if not isinstance(metadata,dict) or not metadata.get("fields"):
        raise SourceError("SCHEMA_CHANGED","ArcGIS layer metadata has no field definitions")
    fields={f["name"]:f for f in metadata["fields"]}
    oid=metadata.get("objectIdField") or metadata.get("objectIdFieldName") or next((f["name"] for f in metadata["fields"] if f.get("type")=="esriFieldTypeOID"),None)
    expected=source.get("parameters",{}).get("expected_fields",[])
    if set(expected)-set(fields):raise SourceError("SCHEMA_CHANGED","Required ArcGIS fields are absent: "+", ".join(sorted(set(expected)-set(fields))))
    query={"f":"json","where":scope["where"]}
    if scope.get("bbox"):
        query.update(geometry=",".join(map(str,scope["bbox"])),geometryType="esriGeometryEnvelope",inSR=scope["in_sr"],spatialRel="esriSpatialRelIntersects")
    count_result=transport.json(endpoint+"/query",params={**query,"returnCountOnly":"true"},kind="query_count")
    expected_count=count_result.get("count") if isinstance(count_result,dict) else None
    if not isinstance(expected_count,int) or expected_count<0:raise SourceError("COUNT_UNAVAILABLE","ArcGIS query count was not returned")
    id_data=transport.json(endpoint+"/query",params={**query,"returnIdsOnly":"true"},kind="query_ids")
    ids=id_data.get("objectIds") if isinstance(id_data,dict) else None
    if ids is None and expected_count==0 and isinstance(id_data,dict) and "objectIds" in id_data:
        ids=[]
    if not isinstance(ids,list):raise SourceError("IDS_UNAVAILABLE","ArcGIS object ID enumeration is required to establish this collection scope")
    ids=sorted(ids,key=lambda v:(isinstance(v,str),v))
    issues=[]
    if len(ids)!=expected_count or len(set(ids))!=len(ids) or id_data.get("exceededTransferLimit"):
        issues.append({"code":"COUNT_ID_MISMATCH","message":"Count and object ID enumeration do not reconcile; source may have changed or truncated"})
    desired=list(dict.fromkeys(ids))[:max_records]
    page_size=min(200,max(1,int(source.get("parameters",{}).get("page_size",200))),int(metadata.get("maxRecordCount",1000) or 1000))
    results=[];seen={};invalid_geometry=False
    for start in range(0,len(desired),page_size):
        chunk=desired[start:start+page_size]
        params={"f":"json","objectIds":",".join(map(str,chunk)),"outFields":"*","returnGeometry":"true","outSR":scope["out_sr"]}
        if oid:params["orderByFields"]=f"{oid} ASC"
        data=transport.json(endpoint+"/query",params=params,kind=f"features_{start}")
        if not isinstance(data,dict) or not isinstance(data.get("features"),list):raise SourceError("SCHEMA_CHANGED","ArcGIS feature page is malformed")
        if data.get("exceededTransferLimit"):issues.append({"code":"PAGE_TRUNCATED","message":"Server truncated an object-ID batch; collection cannot be complete"})
        for feature in data["features"]:
            attrs=feature.get("attributes",{})
            key=attrs.get(oid) if oid else feature.get("id")
            if key is None:raise SourceError("MISSING_FEATURE_ID","ArcGIS feature lacks its declared object ID")
            signature=digest(feature)
            if key in seen:
                if seen[key]!=signature:issues.append({"code":"CONFLICTING_DUPLICATE","message":"One feature ID returned different content"})
                continue
            if key not in chunk:issues.append({"code":"UNEXPECTED_FEATURE_ID","message":"Source returned a feature outside the requested object IDs"});continue
            seen[key]=signature
            raw_geom=feature.get("geometry");geom=None;geom_error=None
            try:geom=esri_to_geojson(raw_geom)
            except SourceError as exc:geom_error={"code":exc.code,"message":str(exc)};invalid_geometry=True
            sr=data.get("spatialReference") or (raw_geom or {}).get("spatialReference") or {"wkid":scope["out_sr"]}
            results.append({"source_id":source["source_id"],"source_record_id":str(key),"attributes":attrs,
                            "geometry":geom,"geometry_format":"geojson_shape","source_geometry":raw_geom,
                            "crs":sr,"geometry_status":"INVALID" if geom_error else ("PRESENT" if geom else "MISSING"),"geometry_error":geom_error})
    if len(results)!=len(desired):issues.append({"code":"FEATURE_COUNT_MISMATCH","message":"Some enumerated source features were not returned"})
    if invalid_geometry:issues.append({"code":"INVALID_GEOMETRY","message":"At least one geometry was retained raw but could not be validated/converted"})
    complete=len(results)==expected_count and not issues and len(ids)<=max_records
    schema={"fields":metadata["fields"],"object_id_field":oid,"native_crs":metadata.get("extent",{}).get("spatialReference") or metadata.get("sourceSpatialReference"),
            "output_crs":scope["out_sr"],"geometry_type":metadata.get("geometryType"),"source_last_edit":metadata.get("editingInfo",{}).get("lastEditDate"),
            "copyright_text":metadata.get("copyrightText"),"description":metadata.get("description"),"metadata_hash":digest(metadata)}
    return results,schema,{"status":"COMPLETE" if complete else "PARTIAL","expected_count":expected_count,"returned_count":len(results),"limit_reached":expected_count>max_records,"query_scope":scope},issues


def _socrata(source,transport,bounds,max_records):
    endpoint=source["endpoint"]
    if not re.search(r"/resource/[a-z0-9]{4}-[a-z0-9]{4}\.json",endpoint,re.I):
        raise SourceError("TABLE_ENDPOINT_REQUIRED","Use a Socrata resource JSON endpoint; catalogue/blob assets require a file adapter")
    p=source.get("parameters",{})
    where=bounds.get("where",p.get("where"))
    if where is not None and (not isinstance(where,str) or not where.strip()):
        raise SourceError("INVALID_BOUNDS","where must be a non-empty source query string")
    params={"$where":where} if where else {}
    count=transport.json(endpoint,params={**params,"$select":"count(*) AS total"},kind="query_count")
    try:expected=int(count[0]["total"])
    except (TypeError,KeyError,IndexError,ValueError) as exc:raise SourceError("COUNT_UNAVAILABLE","Socrata query count was not returned") from exc
    page_size=min(5000,max(1,int(p.get("page_size",1000))))
    out=[];seen={};issues=[];offset=0
    while offset<expected and len(out)<max_records:
        size=min(page_size,max_records-len(out))
        data=transport.json(endpoint,params={**params,"$select":p.get("select","*, :id AS __socrata_row_id"),"$order":p.get("order_by",":id"),"$limit":size,"$offset":offset},kind=f"rows_{offset}")
        if not isinstance(data,list):raise SourceError("INVALID_RESPONSE","Socrata table request did not return an array")
        if not data:break
        if len(data)>size:
            issues.append({"code":"SERVER_PAGE_OVERSIZE","message":"Source returned more rows than requested; row cap was enforced locally"})
            data=data[:size]
        added=0
        for row in data:
            if not isinstance(row,dict):raise SourceError("INVALID_RESPONSE","Socrata row is not an object")
            key=row.get("__socrata_row_id",row.get(p.get("primary_key","id")))
            if key is None:raise SourceError("MISSING_ROW_ID","Socrata row lacks a stable source identifier")
            key=str(key);h=digest(row)
            if key in seen:
                issues.append({"code":"DUPLICATE_PAGE_RECORD","message":"Repeated source row across pages; source stability is not established"})
                if seen[key]!=h:issues.append({"code":"CONFLICTING_DUPLICATE","message":"Repeated source row changed during collection"})
                continue
            seen[key]=h;added+=1
            out.append({"source_id":source["source_id"],"source_record_id":key,"attributes":row,"geometry":None,"crs":None})
        offset+=len(data)
        if added==0:break
    if len(out)<min(expected,max_records):
        issues.append({"code":"ROW_COUNT_MISMATCH","message":"Fewer distinct source rows returned than the count and requested limit require"})
    complete=len(out)==expected and not issues
    return out,{"fields":sorted({k for r in out for k in r["attributes"]}),"record_identity":"Socrata row ID"}, {"status":"COMPLETE" if complete else "PARTIAL","expected_count":expected,"returned_count":len(out),"limit_reached":len(out)>=max_records and expected>len(out),"query_scope":{"where":where}},issues


def _file_body(source,transport,suffix,accept=None):
    p=source.get("parameters",{})
    if p.get("local_path"):
        return transport.local(p["local_path"],suffix=suffix)
    endpoint=p.get("file_url") or source.get("endpoint")
    if not endpoint:raise SourceError("ENDPOINT_REQUIRED","No source endpoint or selected local file")
    return transport.fetch(endpoint,params=p.get("query",{}),kind="published_file",suffix=suffix,accept=accept)


def _file_adapter(source,transport,bounds,max_records):
    adapter=source["adapter"];p=source.get("parameters",{})
    if adapter=="rba_csv":
        body=_file_body(source,transport,"csv","text/csv")
        records,schema=parse_rba_csv(body,series_ids=p.get("series_ids"))
    elif adapter=="sdmx_csv":
        body=_file_body(source,transport,"csv","text/csv, application/vnd.sdmx.data+csv;version=1.0")
        records,schema=parse_sdmx_csv(body)
    elif adapter=="crime_xlsx":
        endpoint=source.get("endpoint","")
        discover=p.get("discover_latest") or (not p.get("file_url") and "/api/views/" in endpoint and "/files/" not in endpoint)
        catalogue_meta=None
        if discover and not p.get("local_path"):
            catalogue_id=p.get("catalogue_id")
            if not catalogue_id:
                match=re.search(r"/api/views/([a-z0-9]{4}-[a-z0-9]{4})",endpoint,re.I)
                catalogue_id=match.group(1) if match else None
            if not catalogue_id or not re.fullmatch(r"[a-z0-9]{4}-[a-z0-9]{4}",catalogue_id,re.I):
                raise SourceError("CATALOGUE_ID_REQUIRED","Crime asset discovery requires a verified Socrata catalogue ID")
            parts=urlsplit(endpoint)
            catalogue_url=urlunsplit((parts.scheme,parts.netloc,"/api/views/"+catalogue_id+".json","",""))
            meta=transport.json(catalogue_url,kind="catalogue_metadata")
            catalogue_meta=meta
            asset=meta.get("blobId") if isinstance(meta,dict) else None
            if not asset:raise SourceError("FILE_LINK_REQUIRED","Crime asset is a workbook; configure its verified file URL after catalogue discovery")
            name=meta.get("blobFilename","crime.xlsx")
            file_url=urlunsplit((parts.scheme,parts.netloc,"/api/views/"+catalogue_id+"/files/"+quote(str(asset),safe=""),"download=true&filename="+quote(str(name)),""))
            source={**source,"parameters":{**p,"file_url":file_url}}
        body=_file_body(source,transport,"xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        records,schema=parse_crime_xlsx(body,area=bounds.get("area",p.get("area")))
        schema["catalogue_metadata"]=catalogue_meta
        schema["expected_vintage"]=p.get("expected_vintage")
        schema["actual_last_period"]=schema["periods"][-1]
    elif adapter=="gtfs_zip":
        body=_file_body(source,transport,"zip","application/zip")
        records,schema=parse_gtfs_zip(body,max_records=max_records)
    elif adapter=="file_download":
        suffix=p.get("format",Path(urlsplit(source.get("endpoint","")).path).suffix.lstrip('.') or "bin")
        body=_file_body(source,transport,suffix)
        content_type=(transport.raw_files[-1].get("content_type") or "").lower()
        if "text/html" in content_type or body.lstrip().lower().startswith((b"<!doctype html",b"<html")):
            return [],{"format":"HTML reference page","parse_status":"RAW_ONLY"},{"status":"REFERENCE_CAPTURED","expected_count":None,"returned_count":0,"limit_reached":False},[]
        return [],{"format":suffix,"parse_status":"RAW_ONLY"},{"status":"FILE_CAPTURED","expected_count":None,"returned_count":0,"limit_reached":False},[]
    else:raise SourceError("UNSUPPORTED_ADAPTER",f"Adapter {adapter} is not implemented")
    if bounds.get("start_period"):
        records=[r for r in records if str(r.get("period",""))>=str(bounds["start_period"])]
    if bounds.get("end_period"):
        records=[r for r in records if str(r.get("period",""))<=str(bounds["end_period"])]
    expected=schema.get("total_rows",len(records))
    limited=records[:max_records]
    for row in limited:row.setdefault("source_id",source["source_id"])
    return limited,schema,{"status":"COMPLETE" if expected<=max_records else "PARTIAL","expected_count":expected,"returned_count":len(limited),"limit_reached":expected>max_records,"query_scope":bounds},[]


def _generic(source,transport,bounds,max_records):
    p=source.get("parameters",{})
    if p.get("local_path"):
        try:data=json.loads(transport.local(p["local_path"],suffix="json"))
        except json.JSONDecodeError as exc:raise SourceError("INVALID_JSON","Local source is not valid JSON") from exc
    else:data=transport.json(source["endpoint"],params=p.get("query",{}),kind="json_response")
    for part in p.get("records_path","").split('.'):
        if part:
            if not isinstance(data,dict) or part not in data:raise SourceError("SCHEMA_CHANGED","Configured record path is absent")
            data=data[part]
    records=data if isinstance(data,list) else [data]
    records=[{"source_id":source["source_id"],"attributes":r} for r in records[:max_records]]
    return records,{"format":"JSON","parse_scope":"source-preserving; no domain meaning inferred"},{"status":"UNKNOWN","returned_count":len(records),"expected_count":None,"limit_reached":len(records)>=max_records},[]


def _discovery(source,transport):
    """Capture a catalogue or reference document without producing property facts."""
    body=_file_body(source,transport,"bin","application/json, application/xml, text/html;q=0.9, */*;q=0.1")
    schema={"format":"reference document","parse_status":"RAW_ONLY","property_facts":False}
    try:
        data=json.loads(body)
        if isinstance(data,dict) and (data.get("error") or data.get("success") is False):
            raise SourceError("SERVICE_ERROR","Discovery catalogue returned an application error")
        schema.update(format="JSON catalogue",top_level_keys=sorted(data) if isinstance(data,dict) else None)
    except (json.JSONDecodeError,UnicodeDecodeError):
        pass
    return [],schema,{"status":"REFERENCE_CAPTURED","expected_count":None,"returned_count":0,"limit_reached":False},[]


def collect(source, output_dir, *, bounds=None, max_records=1000, max_bytes=20_000_000):
    """Collect an explicitly selected registry source into immutable snapshots.

    `enabled` controls scheduling elsewhere; this explicit operation can inspect a
    disabled source without silently activating it. Configured local files permit
    offline import. Caller-supplied endpoint overrides are never accepted in bounds.
    """
    bounds=dict(bounds or {})
    if not isinstance(source,dict) or not source.get("source_id") or not source.get("adapter"):
        raise ValueError("Source contract requires source_id and adapter")
    if not isinstance(max_records,int) or isinstance(max_records,bool) or not 1<=max_records<=1_000_000:
        raise ValueError("max_records must be between1 and1,000,000")
    if not isinstance(max_bytes,int) or isinstance(max_bytes,bool) or not 1024<=max_bytes<=250_000_000:
        raise ValueError("max_bytes must be between1KB and250MB")
    allowed_bounds={
        "arcgis":{"where","bbox","in_sr","out_sr"},
        "socrata":{"where"},
        "rba_csv":{"start_period","end_period"},
        "crime_xlsx":{"area","start_period","end_period"},
        "sdmx_csv":{"start_period","end_period"},
    }.get(source["adapter"],set())
    if set(bounds)-allowed_bounds:
        raise ValueError("Bounds contains unsupported keys; endpoints and auth cannot be overridden")
    # Credentials are environment references, never literal config/query values.
    query=source.get("parameters",{}).get("query",{})
    if any(SENSITIVE.search(str(k)) for k in query):
        raise ValueError("Credentials in parameters.query are forbidden; use auth_env.query references")
    result={"source_id":source["source_id"],"snapshot_id":None,"adapter_version":ADAPTER_VERSION,
            "status":"UNAVAILABLE","retrieved_at":datetime.now(timezone.utc).isoformat(),
            "source_published_at":source.get("published_at"),"raw_files":[],"records":[],"errors":[],"schema":{},
            "coverage":{"status":"NOT_ESTABLISHED","scope":bounds,"reason":"Collection does not prove geographic or mechanism coverage"},
            "completeness":{"status":"UNKNOWN","expected_count":None,"returned_count":0,"limit_reached":False},
            "rights_status":source.get("licence_status","UNVERIFIED"),"rights":source.get("rights",{}),
            "faithful_historical_replay":False}
    adapter=source["adapter"]
    transport=None
    try:
        if adapter=="manual":
            result["status"]="ACCESS_REQUIRED" if source.get("access_status") in {"restricted","credentials_required","manual_request","NEEDS_API_KEY"} else "MANUAL_INPUT_REQUIRED"
            result["errors"].append({"code":"MANUAL_SOURCE","message":"Supply the required authorised document or structured input"})
            return result
        if adapter not in {"arcgis","socrata","rba_csv","crime_xlsx","generic_json","file_download","sdmx_csv","gtfs_zip","discovery"}:
            result["status"]="UNSUPPORTED"
            result["errors"].append({"code":"UNSUPPORTED_ADAPTER","message":f"No collector for adapter {adapter}"})
            return result
        if source.get("rights",{}).get("retain_raw") is not True:
            result["status"]="POLICY_REVIEW_REQUIRED"
            result["errors"].append({"code":"RAW_RETENTION_NOT_AUTHORISED","message":"Source contract must explicitly authorise raw retention before any source data is fetched or copied"})
            return result
        access=str(source.get("access_status","")).lower()
        if any(x in access for x in ("restricted","credentials_required","needs_api_key")) and not (source.get("auth_env") or source.get("parameters",{}).get("auth_env") or source.get("parameters",{}).get("local_path")):
            raise SourceError("CREDENTIALS_REQUIRED","This source requires configured authorised access")
        parameters=source.get("parameters",{})
        if any(k in parameters for k in ("username_env","password_env","api_key_env")) and not (source.get("auth_env") or parameters.get("auth_env") or parameters.get("local_path")):
            raise SourceError("CREDENTIALS_REQUIRED","Credential variable names require a verified auth_env header/basic/query mapping")
        transport=Transport(source,output_dir,max_bytes)
        if adapter=="arcgis":records,schema,complete,issues=_arcgis(source,transport,bounds,max_records)
        elif adapter=="socrata":records,schema,complete,issues=_socrata(source,transport,bounds,max_records)
        elif adapter=="generic_json":records,schema,complete,issues=_generic(source,transport,bounds,max_records)
        elif adapter=="discovery":records,schema,complete,issues=_discovery(source,transport)
        else:records,schema,complete,issues=_file_adapter(source,transport,bounds,max_records)
        result.update(records=records,schema=schema,completeness=complete,errors=issues)
        result["status"]="REFERENCE_ONLY" if complete["status"]=="REFERENCE_CAPTURED" else ("SUCCESS" if complete["status"] in {"COMPLETE","FILE_CAPTURED"} else "PARTIAL")
    except SourceError as exc:
        result["errors"].append({"code":exc.code,"message":transport.redact(str(exc)) if transport else str(exc),"http_status":exc.http_status})
        result["status"]="ACCESS_REQUIRED" if exc.code in {"CREDENTIALS_REQUIRED","ACCESS_DENIED"} else "UNAVAILABLE"
        if transport and transport.raw_files:result["completeness"]["status"]="PARTIAL"
    except (ValueError,TypeError,KeyError,UnicodeDecodeError) as exc:
        result["errors"].append({"code":"INVALID_RESPONSE","message":"Source/configuration could not be parsed; retained raw evidence requires review"})
        result["status"]="INVALID_RESPONSE"
    finally:
        if transport:
            result["raw_files"]=transport.raw_files
            result["requests"]=transport.requests
            result["network_resolution"]=transport.resolution_events
            result["bytes_received"]=transport.consumed
            transport.close()
        stable={"source_id":source["source_id"],"adapter":adapter,"adapter_version":ADAPTER_VERSION,
                "scope":bounds,"endpoint":safe_url(source.get("endpoint", "")),
                "rights_contract_hash":digest(source.get("rights",{})),
                "source_published_at":result["source_published_at"],
                "parameters":{k:(safe_url(v) if k=="file_url" else v) for k,v in source.get("parameters",{}).items() if k not in {"auth_env","local_path"}},
                "payloads":[{"kind":r["kind"],"sha256":r["sha256"]} for r in result["raw_files"]],
                "status":result["status"],"completeness":result["completeness"],"records_hash":digest(result["records"])}
        result["snapshot_id"]="sha256:"+digest(stable)
        out=Path(output_dir)
        manifest=out/"snapshots"/(result["snapshot_id"].split(':',1)[1]+".json")
        # Snapshot definition is content-addressed. Separate capture receipts keep
        # wall-clock retrieval facts and do not change the deterministic snapshot.
        atomic_write(manifest,canonical_bytes(stable))
        result["snapshot_manifest"]=str(manifest)
        receipt=out/"receipts"/(digest({"snapshot":result["snapshot_id"],"time":result["retrieved_at"]})+".json")
        atomic_write(receipt,canonical_bytes(result))
        result["receipt_path"]=str(receipt)
    return result
