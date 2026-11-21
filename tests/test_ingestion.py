"""Collector gates: a successful HTTP response is not a complete risk input."""
from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

import httpx
import pytest
from shapely.geometry import shape

import riskengine.ingestion as ingestion
from riskengine.adapters import common
from riskengine.adapters.common import SourceError, Transport
from riskengine.adapters.parsers import (
    esri_to_geojson, parse_crime_xlsx, parse_gtfs_zip, parse_rba_csv,
    parse_sdmx_csv,
)


@pytest.fixture
def fake_http(monkeypatch):
    clients = []
    calls, sleeps = [], []

    def configure(handler):
        def tracked(request):
            calls.append(request)
            return handler(request)
        client = httpx.Client(transport=httpx.MockTransport(tracked))
        clients.append(client)
        monkeypatch.setattr(common, "public_url", lambda *a, **k: None)
        monkeypatch.setattr(ingestion, "Transport", lambda source, output_dir, max_bytes:
                            Transport(source, output_dir, max_bytes, client=client, sleep=sleeps.append))
        return calls, sleeps

    yield configure
    for client in clients:
        client.close()


def source(adapter="arcgis", **parameters):
    endpoints = {
        "arcgis": "https://source.example/arcgis/rest/services/Test/FeatureServer/0",
        "socrata": "https://source.example/resource/abcd-1234.json",
        "generic_json": "https://source.example/data.json",
    }
    return {"source_id": "test_source", "adapter": adapter,
            "endpoint": endpoints.get(adapter, "https://source.example/file"),
            "licence_status": "UNVERIFIED", "rights": {"retain_raw": True},
            "parameters": parameters}


def arcgis_handler(total=5, *, duplicate=False, empty_null=False):
    def handle(request):
        q = request.url.params
        if request.url.path.endswith("/0"):
            return httpx.Response(200, json={
                "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
                "objectIdField": "OBJECTID", "maxRecordCount": 2,
                "geometryType": "esriGeometryPoint",
                "extent": {"spatialReference": {"wkid": 7855}},
            })
        if q.get("returnCountOnly"):
            return httpx.Response(200, json={"count": total})
        if q.get("returnIdsOnly"):
            return httpx.Response(200, json={"objectIds": None if empty_null else list(range(1, total + 1))})
        ids = [int(x) for x in q["objectIds"].split(",")]
        features = [{"attributes": {"OBJECTID": i, "name": "original"},
                     "geometry": {"x": 149 + i / 1000, "y": -35}} for i in ids]
        if duplicate:
            features.append({"attributes": {"OBJECTID": ids[0], "name": "changed"},
                             "geometry": {"x": 149, "y": -35}})
        return httpx.Response(200, json={"features": features, "spatialReference": {"wkid": 4326}})
    return handle


def test_arcgis_paging_reconciles_count_and_keeps_coverage_unknown(tmp_path, fake_http):
    calls, _ = fake_http(arcgis_handler())
    result = ingestion.collect(source(page_size=2), tmp_path, max_records=10,
                               bounds={"where": "DIVISION = 'KINGSTON'"})
    assert result["status"] == "SUCCESS"
    assert result["completeness"]["status"] == "COMPLETE"
    assert result["completeness"]["returned_count"] == 5
    assert result["coverage"]["status"] == "NOT_ESTABLISHED"
    assert result["rights_status"] == "UNVERIFIED"
    assert result["faithful_historical_replay"] is False
    assert result["source_published_at"] is None
    batches = [r.url.params["objectIds"] for r in calls if "objectIds" in r.url.params]
    assert batches == ["1,2", "3,4", "5"]
    assert result["schema"]["native_crs"] == {"wkid": 7855}
    assert result["records"][0]["crs"] == {"wkid": 4326}
    assert result["records"][0]["source_geometry"] == {"x": 149.001, "y": -35}
    assert Path(result["snapshot_manifest"]).is_file()


def test_arcgis_record_cap_is_partial_not_complete(tmp_path, fake_http):
    fake_http(arcgis_handler())
    result = ingestion.collect(source(), tmp_path, max_records=3)
    assert result["status"] == "PARTIAL"
    assert len(result["records"]) == 3
    assert result["completeness"]["expected_count"] == 5
    assert result["completeness"]["limit_reached"] is True


def test_arcgis_zero_results_never_mean_clear(tmp_path, fake_http):
    fake_http(arcgis_handler(total=0, empty_null=True))
    result = ingestion.collect(source(), tmp_path)
    assert result["status"] == "SUCCESS"
    assert result["records"] == []
    assert result["completeness"]["status"] == "COMPLETE"
    assert result["coverage"]["status"] == "NOT_ESTABLISHED"


def test_conflicting_duplicate_prevents_complete_claim(tmp_path, fake_http):
    fake_http(arcgis_handler(total=2, duplicate=True))
    result = ingestion.collect(source(), tmp_path)
    assert result["status"] == "PARTIAL"
    assert len(result["records"]) == 2
    assert "CONFLICTING_DUPLICATE" in {e["code"] for e in result["errors"]}


def test_http_200_service_error_retains_evidence_without_facts(tmp_path, fake_http):
    fake_http(lambda r: httpx.Response(200, json={"error": {"code": 400, "message": "Invalid query"}}))
    result = ingestion.collect(source(), tmp_path)
    assert result["status"] == "UNAVAILABLE"
    assert result["records"] == []
    assert result["errors"][0]["code"] == "SERVICE_ERROR"
    assert len(result["raw_files"]) == 1


def test_retry_after_is_respected_and_bounded(tmp_path, fake_http):
    attempts = []
    def handle(request):
        attempts.append(1)
        return httpx.Response(429, headers={"Retry-After": "2"}) if len(attempts) < 3 else httpx.Response(200, json={"ok": True})
    _, sleeps = fake_http(handle)
    result = ingestion.collect(source("generic_json"), tmp_path)
    assert len(attempts) == 3
    assert sleeps == [2.0, 2.0]
    assert result["status"] == "PARTIAL"  # Generic JSON cannot prove pagination completeness.
    assert result["completeness"]["status"] == "UNKNOWN"


def test_retry_exhaustion_does_not_fake_success(tmp_path, fake_http):
    calls, sleeps = fake_http(lambda r: httpx.Response(503))
    result = ingestion.collect(source("generic_json", retries=1), tmp_path)
    assert len(calls) == 2 and sleeps == [1]
    assert result["status"] == "UNAVAILABLE"
    assert result["errors"][0]["http_status"] == 503


def test_long_retry_after_defers_instead_of_retrying_early(tmp_path, fake_http):
    calls, sleeps = fake_http(lambda r: httpx.Response(429, headers={"Retry-After": "120"}))
    result = ingestion.collect(source("generic_json"), tmp_path)
    assert len(calls) == 1 and sleeps == []
    assert result["errors"][0]["code"] == "RETRY_DEFERRED"


def test_byte_budget_covers_metadata_and_pages(tmp_path, fake_http):
    normal = arcgis_handler(total=1)
    def handle(request):
        if "objectIds" in request.url.params:
            return httpx.Response(200, json={"features": [{"attributes": {"OBJECTID": 1, "huge": "x" * 2000}}]})
        return normal(request)
    fake_http(handle)
    result = ingestion.collect(source(), tmp_path, max_bytes=1024)
    assert result["status"] == "UNAVAILABLE"
    assert result["completeness"]["status"] == "PARTIAL"
    assert result["errors"][0]["code"] == "BYTE_LIMIT"
    assert len(result["raw_files"]) == 3
    assert not result["records"]


def test_identical_payload_scope_has_stable_snapshot_new_receipt(tmp_path, fake_http):
    fake_http(arcgis_handler(total=1))
    first = ingestion.collect(source(), tmp_path)
    second = ingestion.collect(source(), tmp_path)
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["receipt_path"] != second["receipt_path"]
    assert first["retrieved_at"] != second["retrieved_at"]
    assert len(list((tmp_path / "snapshots").glob("*.json"))) == 1


def test_socrata_paging_and_count(tmp_path, fake_http):
    def handle(request):
        q = request.url.params
        if q["$select"].startswith("count"):
            return httpx.Response(200, json=[{"total": "5"}])
        start, limit = int(q["$offset"]), int(q["$limit"])
        return httpx.Response(200, json=[{"__socrata_row_id": str(i), "value": i} for i in range(start, min(start + limit, 5))])
    calls, _ = fake_http(handle)
    result = ingestion.collect(source("socrata", page_size=2), tmp_path, max_records=10)
    assert result["status"] == "SUCCESS"
    assert len(result["records"]) == 5
    assert [r.url.params["$offset"] for r in calls if "$offset" in r.url.params] == ["0", "2", "4"]


def test_socrata_duplicate_page_never_complete(tmp_path, fake_http):
    fake_http(lambda r: httpx.Response(200, json=[{"total": "4"}] if r.url.params["$select"].startswith("count") else [{"__socrata_row_id": "1"}, {"__socrata_row_id": "2"}]))
    result = ingestion.collect(source("socrata", page_size=2), tmp_path)
    assert result["status"] == "PARTIAL"
    assert len(result["records"]) == 2
    assert "DUPLICATE_PAGE_RECORD" in {e["code"] for e in result["errors"]}


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1/a", "http://169.254.169.254/metadata", "http://[::1]/a", "https://8.8.8.8/a", "file:///etc/passwd", "https://localhost/a"])
def test_private_endpoints_rejected(endpoint):
    with pytest.raises(SourceError):
        common.public_url(endpoint)


def test_bounds_cannot_override_endpoint_or_silently_ignore_filter(tmp_path):
    with pytest.raises(ValueError):
        ingestion.collect(source(), tmp_path, bounds={"endpoint": "http://127.0.0.1"})
    with pytest.raises(ValueError):
        ingestion.collect(source("socrata"), tmp_path, bounds={"bbox": [1, 2, 3, 4]})


def test_existing_query_and_credentials_env_preserved_redacted(tmp_path, fake_http, monkeypatch):
    monkeypatch.setenv("TEST_FEED_TOKEN", "do-not-persist-this-secret")
    calls, _ = fake_http(lambda r: httpx.Response(200, json={"ok": True}))
    src = source("generic_json")
    src["endpoint"] += "?download=true"
    src["auth_env"] = {"query": {"token": "TEST_FEED_TOKEN"}}
    result = ingestion.collect(src, tmp_path)
    assert calls[0].url.params["download"] == "true"
    assert calls[0].url.params["token"] == "do-not-persist-this-secret"
    assert "do-not-persist-this-secret" not in json.dumps(result)
    assert "do-not-persist-this-secret" not in Path(result["receipt_path"]).read_text()


def test_literal_query_secrets_are_not_accepted(tmp_path):
    with pytest.raises(ValueError, match="auth_env"):
        ingestion.collect(source("generic_json", query={"api_key": "unsafe"}), tmp_path)


@pytest.mark.parametrize("proxies,mode", [
    ({"https": "http://https-proxy.example:8080", "all": "socks5h://proxy.example:1080"}, "REGISTERED_HTTPS_CONNECT_PROXY_DNS"),
    ({"all": "socks5h://proxy.example:1080"}, "REGISTERED_HTTPS_SOCKS_REMOTE_DNS"),
])
def test_registered_https_source_uses_configured_remote_dns(tmp_path, fake_http, monkeypatch, proxies, mode):
    fake_http(lambda r: httpx.Response(200, json={"ok": True}))
    seen = []
    def dns_unavailable(url, *, resolve_dns=True):
        seen.append(resolve_dns)
        if resolve_dns:
            raise SourceError("DNS_FAILED", "No local resolver")
    monkeypatch.setattr(common, "public_url", dns_unavailable)
    monkeypatch.setattr(common, "getproxies", lambda: proxies)
    monkeypatch.setattr(common, "proxy_bypass", lambda host: False)
    result = ingestion.collect(source("generic_json"), tmp_path)
    assert result["status"] == "PARTIAL"  # Valid generic capture; completeness remains unknown.
    assert False in seen
    assert result["network_resolution"] == [{"host": "source.example", "mode": mode}]


def test_https_redirect_downgrade_is_rejected(tmp_path, fake_http):
    calls, _ = fake_http(lambda r: httpx.Response(302, headers={"Location": "http://source.example/file"}))
    result = ingestion.collect(source("generic_json"), tmp_path)
    assert len(calls) == 1
    assert result["errors"][0]["code"] == "INSECURE_REDIRECT"


def test_remote_dns_does_not_allow_unregistered_redirect(tmp_path, fake_http, monkeypatch):
    calls, _ = fake_http(lambda r: httpx.Response(302, headers={"Location": "https://unregistered.example/file"}))
    monkeypatch.setattr(common, "getproxies", lambda: {"https": "socks5h://proxy.example:1080"})
    result = ingestion.collect(source("generic_json"), tmp_path)
    assert len(calls) == 1
    assert result["errors"][0]["code"] == "UNREGISTERED_HOST"


def test_private_dns_answer_never_falls_back_to_proxy(tmp_path, fake_http, monkeypatch):
    calls, _ = fake_http(lambda r: pytest.fail("Private endpoint must not reach transport"))
    def private(url, **kwargs):
        raise SourceError("PRIVATE_ENDPOINT", "Non-public DNS answer")
    monkeypatch.setattr(common, "public_url", private)
    monkeypatch.setattr(common, "getproxies", lambda: {"https": "socks5h://proxy.example:1080"})
    monkeypatch.setattr(common, "proxy_bypass", lambda host: False)
    result = ingestion.collect(source("generic_json"), tmp_path)
    assert calls == []
    assert result["errors"][0]["code"] == "PRIVATE_ENDPOINT"


def test_source_publication_date_changes_snapshot_identity(tmp_path, fake_http):
    fake_http(arcgis_handler(total=1))
    src = source()
    first = ingestion.collect(src, tmp_path)
    src["published_at"] = "2026-01-01"
    second = ingestion.collect(src, tmp_path)
    assert first["snapshot_id"] != second["snapshot_id"]
    assert second["source_published_at"] == "2026-01-01"


def test_required_credentials_are_explicit_without_network(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_MISSING_FEED_KEY", raising=False)
    src = source("gtfs_zip")
    src["auth_env"] = {"headers": {"X-Api-Key": "TEST_MISSING_FEED_KEY"}}
    result = ingestion.collect(src, tmp_path)
    assert result["status"] == "ACCESS_REQUIRED"
    assert result["errors"][0]["code"] == "CREDENTIALS_REQUIRED"
    assert result["raw_files"] == []


def test_offline_rba_preserves_blanks_units_series_and_publication(tmp_path):
    body = ("Title,Cash Rate Target,Other\nUnits,Per cent,Index\nFrequency,Daily,Monthly\n"
            "Publication date,20-Nov-2026,20-Nov-2026\nSeries ID,FIRMMCRTD,OTHER\n"
            "18-Nov-2026,6,10\n19-Nov-2026,,11\n").encode()
    fixture = tmp_path / "input.csv"
    fixture.write_bytes(body)
    src = source("rba_csv", local_path=str(fixture))
    src["auth_env"] = {"headers": {"X-Api-Key": "UNSET_LOCAL_IMPORT_KEY"}}
    result = ingestion.collect(src, tmp_path / "capture")
    assert result["status"] == "SUCCESS"
    assert result["records"][0]["value"] is None
    assert result["records"][0]["observation_status"] == "MISSING"
    assert result["records"][1]["value"] == "6"
    assert result["records"][1]["value_decimal"] == "0.06"
    assert result["records"][1]["publication_date"] == "2026-11-20"
    assert result["requests"] == []


def test_sdmx_keeps_dimensions_units_multiplier_and_missing_value():
    rows, schema = parse_sdmx_csv(b"FREQ,REGION,TIME_PERIOD,UNIT_MEASURE,UNIT_MULT,OBS_VALUE\nA,ACT,2025,NUMBER,3,12.5\nA,ACT,2026,NUMBER,3,\n")
    assert rows[0]["value"] == "12.5"
    assert rows[0]["unit_multiplier"] == "3"
    assert rows[0]["dimensions"]["REGION"] == "ACT"
    assert rows[1]["value"] is None
    with pytest.raises(SourceError, match="discovery"):
        parse_sdmx_csv(b"<?xml version='1.0'?><Dataflows/>")


def test_esri_ring_hole_and_island_keep_correct_topology():
    exterior = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]]
    island = [[3, 3], [4, 3], [4, 4], [3, 4], [3, 3]]
    result = esri_to_geojson({"rings": [hole, exterior, island]})
    assert result["type"] == "MultiPolygon"
    assert shape(result).area == 65
    assert shape(result).is_valid


def test_esri_overlapping_exterior_rings_rejected():
    with pytest.raises(SourceError, match="overlap"):
        esri_to_geojson({"rings": [[[0, 0], [3, 0], [3, 3], [0, 3], [0, 0]],
                                     [[2, 2], [5, 2], [5, 5], [2, 5], [2, 2]]]})


def gtfs_bytes():
    buffer = io.BytesIO()
    tables = {
        "agency.txt": "agency_name,agency_url,agency_timezone\nTest,https://example.org,Australia/Sydney\n",
        "routes.txt": "route_id,route_short_name,route_type\nR,1,3\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nS,Stop,-35,149\n",
        "trips.txt": "route_id,service_id,trip_id\nR,WK,T\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT,25:10:00,25:11:00,S,1\n",
        "calendar_dates.txt": "service_id,date,exception_type\nWK,20261120,1\n",
    }
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in tables.items():
            archive.writestr(name, value)
    return buffer.getvalue()


def test_gtfs_calendar_dates_and_over_midnight_service_time():
    rows, schema = parse_gtfs_zip(gtfs_bytes(), max_records=10)
    assert schema["total_rows"] == 6
    assert schema["record_cap_reached"] is False
    times = next(r for r in rows if r["table"] == "stop_times.txt")
    assert times["attributes"]["arrival_time"] == "25:10:00"
    rows, schema = parse_gtfs_zip(gtfs_bytes(), max_records=2)
    assert len(rows) == 2 and schema["record_cap_reached"] is True
    with pytest.raises(SourceError, match="expanded"):
        parse_gtfs_zip(gtfs_bytes(), max_expanded_bytes=10)


def test_discovery_is_reference_only_even_if_json_is_valid(tmp_path, fake_http):
    fake_http(lambda r: httpx.Response(200, json={"datasets": [{"title": "Potential dataset"}]}))
    result = ingestion.collect(source("discovery"), tmp_path)
    assert result["status"] == "REFERENCE_ONLY"
    assert result["coverage"]["status"] == "NOT_ESTABLISHED"
    assert result["records"] == []


def test_html_discovery_and_download_page_are_reference_only(tmp_path, fake_http):
    fake_http(lambda r: httpx.Response(200, headers={"content-type": "text/html"}, text="<!doctype html><title>Available downloads</title>"))
    for adapter in ("discovery", "file_download"):
        result = ingestion.collect(source(adapter), tmp_path / adapter)
        assert result["status"] == "REFERENCE_ONLY"
        assert result["records"] == []


@pytest.mark.parametrize("rights", [{}, {"retain_raw": False}])
def test_unapproved_retention_never_fetches_or_copies_source(tmp_path, fake_http, rights):
    calls, _ = fake_http(lambda r: pytest.fail("Policy-blocked source must never be fetched"))
    src = source("generic_json")
    src["rights"] = rights
    result = ingestion.collect(src, tmp_path)
    assert result["status"] == "POLICY_REVIEW_REQUIRED"
    assert result["raw_files"] == []
    assert result["records"] == []
    assert calls == []
    assert not (tmp_path / "raw").exists()
    assert Path(result["snapshot_manifest"]).is_file()


def test_crime_discovers_blob_and_keeps_original_download_query(tmp_path, fake_http):
    data = (Path(__file__).parent / "fixtures/ingestion/act_crime_quarterly_2025q2.xlsx").read_bytes()
    def handle(request):
        if request.url.path == "/api/views/abcd-1234.json":
            return httpx.Response(200, json={"id": "abcd-1234", "viewType": "blobby", "blobId": "asset-id", "blobFilename": "Qtr crime.xlsx"})
        assert request.url.path == "/api/views/abcd-1234/files/asset-id"
        assert request.url.params["download"] == "true"
        assert request.url.params["filename"] == "Qtr crime.xlsx"
        return httpx.Response(200, content=data)
    calls, _ = fake_http(handle)
    src = source("crime_xlsx", catalogue_id="abcd-1234", discover_latest=True)
    result = ingestion.collect(src, tmp_path, bounds={"area": "KINGSTON"})
    assert len(calls) == 2
    assert result["status"] == "SUCCESS"
    assert result["completeness"]["expected_count"] == 874
    assert result["schema"]["actual_last_period"] == "2025-Q2"


def test_blob_catalogue_is_not_treated_as_socrata_table(tmp_path, fake_http):
    calls, _ = fake_http(lambda r: httpx.Response(200, json=[]))
    src = source("socrata")
    src["endpoint"] = "https://source.example/api/views/abcd-1234.json"
    result = ingestion.collect(src, tmp_path)
    assert result["status"] == "UNAVAILABLE"
    assert result["errors"][0]["code"] == "TABLE_ENDPOINT_REQUIRED"
    assert calls == []


def test_crime_published_fixture_stacked_tables_and_infringements():
    path = Path(__file__).parent / "fixtures/ingestion/act_crime_quarterly_2025q2.xlsx"
    rows, schema = parse_crime_xlsx(path.read_bytes(), area="KINGSTON")
    assert len(rows) == 874
    assert sum(r["category_family"] == "reported_offence" for r in rows) == 644
    assert sum(r["category_family"] == "infringement_activity" for r in rows) == 230
    assert len(schema["categories"]) == 19
    assert schema["periods"][0] == "2014-Q1"
    assert schema["periods"][-1] == "2025-Q2"
    assert schema["rates_calculated"] is False
    assert all(r["source_cell"] and r["source_sheet"] == "Inner South" for r in rows)


def test_registry_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"sources": [source(), source()]}))
    with pytest.raises(ValueError, match="unique"):
        ingestion.load_registry(path)
