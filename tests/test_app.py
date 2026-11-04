import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ADMIN_KEY = "test_admin_key_0001"


@pytest.fixture
def client(tmp_path, monkeypatch):
    # The tests provide their own settings, so they never see what the real server has.
    monkeypatch.setenv("PAYMENTS_API_URL", "http://payments.test.example.test/v1")
    monkeypatch.setenv("ACME_DB", str(tmp_path / "shop.db"))
    monkeypatch.setenv("ACME_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("ACME_ADMIN_KEYS", ADMIN_KEY)
    monkeypatch.setenv("ACME_VERSION", "test123")
    from app.main import app

    with TestClient(app) as c:
        yield c


def read_log(tmp_path: Path, stream: str) -> list:
    path = tmp_path / "logs" / f"{stream}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "version": "test123"}


def test_storefront_lists_products_and_version(client):
    r = client.get("/")
    assert r.status_code == 200
    for name in ("Starter", "Team", "Business"):
        assert name in r.text
    assert "test123" in r.text


def test_checkout_creates_order(client, tmp_path):
    r = client.post("/checkout", json={"product_id": 2, "qty": 1, "region": "EU"})
    assert r.status_code == 200
    body = r.json()
    assert body["order_id"] >= 1
    assert body["currency"] == "EUR"
    assert body["amount"] == 49
    entries = read_log(tmp_path, "app")
    assert any(e["path"] == "/checkout" and e["status"] == 200 for e in entries)


def test_checkout_unknown_product(client):
    r = client.post("/checkout", json={"product_id": 99, "region": "US"})
    assert r.status_code == 404


def test_crash_is_logged(client, tmp_path, monkeypatch):
    monkeypatch.delenv("PAYMENTS_API_URL")
    r = client.post("/checkout", json={"product_id": 1, "region": "US"})
    assert r.status_code == 500
    crash = [e for e in read_log(tmp_path, "app") if e.get("level") == "ERROR"][-1]
    assert crash["error"].startswith("KeyError")
    assert crash["where"].startswith("config.py:")


def test_admin_env_lists_names_only(client):
    r = client.get("/admin/env", headers={"x-api-key": ADMIN_KEY})
    assert r.status_code == 200
    names = r.json()["names"]
    assert "ACME_ADMIN_KEYS" in names
    assert ADMIN_KEY not in r.text


def test_admin_rejects_bad_key_and_audits(client, tmp_path):
    r = client.get("/admin/env", headers={"x-api-key": "nope"})
    assert r.status_code == 403
    audit = read_log(tmp_path, "audit")[-1]
    assert audit["allowed"] is False
    assert audit["action"] == "list_env_vars"


def test_admin_audit_uses_forwarded_ip(client, tmp_path):
    r = client.post(
        "/admin/keys?name=ci",
        headers={"x-api-key": ADMIN_KEY, "X-Forwarded-For": "198.51.100.7, 10.0.0.1"},
    )
    assert r.status_code == 200
    audit = read_log(tmp_path, "audit")[-1]
    assert audit["ip"] == "198.51.100.7"
    assert audit["action"] == "create_api_key"
    assert audit["new_key"] == "ci"
    assert audit["key_hint"] == ADMIN_KEY[-4:]


def test_revenue_job_runs(client, tmp_path):
    from jobs import daily_revenue

    for region in ("US", "EU", "APAC"):
        client.post("/checkout", json={"product_id": 1, "region": region})
    result = daily_revenue.run()
    # Warnings are acceptable: the job is designed to keep going.
    assert result["status"] in ("SUCCESS", "SUCCESS_WITH_WARNINGS")
    assert result["rows"] == 3
    rows = client.get("/api/revenue").json()["rows"]
    assert len(rows) == 3
