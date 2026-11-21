import re

from fastapi.testclient import TestClient
import pytest

from riskengine.api import create_app
from riskengine.desktop import LocalDashboard

KEY = "a-disposable-secret-for-the-unit-test"
ORIGIN = "http://127.0.0.1:8127"
BROWSER = {"Sec-Fetch-Site": "same-origin", "X-Risk-Dashboard": "1"}


def client_for(directory, dashboard, keys=None):
    app = create_app(directory, keys or {KEY: "demo"}, dashboard=dashboard)
    return TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 51000))


def test_private_desktop_requires_local_launch(tmp_path, monkeypatch):
    desktop = LocalDashboard("desktop", "127.0.0.1", 8127, "demo", tmp_path)
    client = client_for(tmp_path, desktop)
    assert client.get("/v1/cases", headers=BROWSER).status_code == 401
    monkeypatch.setattr("webbrowser.open", lambda _: True)
    desktop.open_browser()
    launch = desktop.launch_path
    code = re.search('name="code" value="([^"]+)"', launch.read_text()).group(1)
    response = client.post("/desktop/open", data={"code": code}, headers={"Origin": "null"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"
    assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
    assert not launch.exists()
    assert client.get("/v1/cases", headers=BROWSER).json() == {"cases": []}
    assert client.post("/desktop/open", data={"code": code}, headers={"Origin": "null"}).status_code == 403
    assert client.get("/v1/cases", headers={**BROWSER, "Authorization": "invalid"}).status_code == 401
    assert client.get("/v1/cases", headers={"Authorization": f"Bearer {KEY}"}).status_code == 200
    assert client.post("/v1/cases", json={}, headers=BROWSER).status_code == 401


def test_sample_directory_and_tenant_are_fixed(tmp_path, monkeypatch):
    directory = tmp_path / "runtime" / "buyer-preview"
    monkeypatch.setenv("RISK_PROJECT_ROOT", str(tmp_path))
    for folder, tenant, host in [(tmp_path, "demo", "127.0.0.1"), (directory, "other", "127.0.0.1"),
                                 (directory, "demo", "0.0.0.0")]:
        with pytest.raises(ValueError):
            LocalDashboard("preview", host, 8127, tenant, folder)
    preview = LocalDashboard("preview", "127.0.0.1", 8127, "demo", directory)
    with pytest.raises(ValueError):
        client_for(directory, preview, {KEY: "demo", KEY + "2": "other"})
    client = client_for(directory, preview)
    assert client.get("/v1/cases", headers=BROWSER).status_code == 200
    for changed in ({"Host": "localhost:8127"}, {"Origin": "http://localhost:8127"},
                    {"Sec-Fetch-Site": "cross-site"}, {"X-Forwarded-For": "127.0.0.1"}):
        assert client.get("/v1/cases", headers={**BROWSER, **changed}).status_code == 401
    assert client.get("/v1/cases").status_code == 401
    assert client.get("/?case=kingston-buyer-example").headers["x-frame-options"] == "DENY"
    assert client.post("/desktop/open").status_code == 404
