"""Step 4: the mock registry's statuses, and the client's behaviour when it is down."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.registry_client import RegistryClient, RegistryRecord
from registry.app.db import Base as RegistryBase
from registry.app.db import IssuedApaar, get_registry_db
from registry.app.main import app as registry_app

API_KEY = "test-registry-key"
ISSUED = [
    ("123456781234", "Rahul Sharma", "2006-03-12"),
    ("987654321098", "Aisha Fatima Khan", "2005-11-02"),
]


@pytest.fixture()
def registry_client() -> TestClient:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    RegistryBase.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    session = maker()
    session.add_all([IssuedApaar(apaar=a, name=n, dob=d) for a, n, d in ISSUED])
    session.commit()

    def override():
        db = maker()
        try:
            yield db
        finally:
            db.close()

    registry_app.dependency_overrides[get_registry_db] = override
    with TestClient(registry_app) as client:
        yield client
    registry_app.dependency_overrides.pop(get_registry_db, None)
    session.close()


def _key() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


# ------------------------------------------------------------------ registry service


def test_health_reports_issued_count(registry_client: TestClient) -> None:
    body = registry_client.get("/health").json()
    assert body["service"] == "registry"
    assert body["issued_count"] == 2


def test_verify_requires_an_api_key(registry_client: TestClient) -> None:
    response = registry_client.post("/verify", json={"apaar": ISSUED[0][0]})
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "BAD_API_KEY"


def test_verify_match(registry_client: TestClient) -> None:
    body = registry_client.post(
        "/verify",
        headers=_key(),
        json={"apaar": "123456781234", "name": "Rahul Sharma", "dob": "2006-03-12"},
    ).json()
    assert body["status"] == "match"
    assert body["apaar_masked"] == "XXXX-XXXX-1234"
    assert body["name_similarity"] == 100
    assert body["dob_match"] is True
    assert body["source"] == "mock_apaar_registry_v1"


def test_verify_tolerates_small_name_differences(registry_client: TestClient) -> None:
    """rapidfuzz >= 90 counts as a match: "Sharma Rahul" is the same person."""
    body = registry_client.post(
        "/verify",
        headers=_key(),
        json={"apaar": "123456781234", "name": "Sharma Rahul", "dob": "2006-03-12"},
    ).json()
    assert body["status"] == "match"


def test_verify_mismatch_on_a_different_name(registry_client: TestClient) -> None:
    body = registry_client.post(
        "/verify",
        headers=_key(),
        json={"apaar": "123456781234", "name": "Vikram Patel", "dob": "2006-03-12"},
    ).json()
    assert body["status"] == "mismatch"
    assert body["name_similarity"] < 90


def test_verify_mismatch_on_a_different_dob(registry_client: TestClient) -> None:
    body = registry_client.post(
        "/verify",
        headers=_key(),
        json={"apaar": "123456781234", "name": "Rahul Sharma", "dob": "2001-01-01"},
    ).json()
    assert body["status"] == "mismatch"
    assert body["dob_match"] is False


def test_verify_not_found(registry_client: TestClient) -> None:
    body = registry_client.post(
        "/verify", headers=_key(), json={"apaar": "111111111111", "name": "Nobody", "dob": "2006-01-01"}
    ).json()
    assert body["status"] == "not_found"


def test_verify_without_name_or_dob_requires_consent(registry_client: TestClient) -> None:
    body = registry_client.post("/verify", headers=_key(), json={"apaar": "123456781234"}).json()
    assert body["status"] == "consent_required"


def test_verify_batch_keeps_refs(registry_client: TestClient) -> None:
    body = registry_client.post(
        "/verify/batch",
        headers=_key(),
        json={
            "records": [
                {"ref": "row-1", "apaar": "123456781234", "name": "Rahul Sharma", "dob": "2006-03-12"},
                {"ref": "row-2", "apaar": "000000000000", "name": "Ghost", "dob": "2006-03-12"},
            ]
        },
    ).json()
    assert body["count"] == 2
    by_ref = {item["ref"]: item["status"] for item in body["results"]}
    assert by_ref == {"row-1": "match", "row-2": "not_found"}


def test_bulk_insert_is_idempotent(registry_client: TestClient) -> None:
    payload = {"records": [{"apaar": "555000111222", "name": "New Student", "dob": "2007-02-02"}]}
    first = registry_client.post("/registry/apaar/bulk", headers=_key(), json=payload).json()
    second = registry_client.post("/registry/apaar/bulk", headers=_key(), json=payload).json()
    assert first["inserted"] == 1
    assert second["inserted"] == 0 and second["skipped_existing"] == 1


# ------------------------------------------------------------------ client


def _forwarding_transport(test_client: TestClient) -> httpx.MockTransport:
    """Forward the sync client's requests into the in-process registry TestClient."""

    def handler(request: httpx.Request) -> httpx.Response:
        response = test_client.request(
            request.method,
            request.url.path,
            content=request.content,
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
        )
        return httpx.Response(response.status_code, content=response.content)

    return httpx.MockTransport(handler)


def _client_against(registry_client: TestClient, api_key: str = API_KEY) -> RegistryClient:
    """Point the typed client at the in-process registry app."""
    return RegistryClient(
        base_url="http://registry.test",
        api_key=api_key,
        transport=_forwarding_transport(registry_client),
    )


def test_client_batch_maps_results_back_to_rows(registry_client: TestClient) -> None:
    client = _client_against(registry_client)
    results = client.verify_batch(
        [
            RegistryRecord(apaar="123456781234", name="Rahul Sharma", dob="2006-03-12", ref="r1"),
            RegistryRecord(apaar="123123123123", name="Unknown Person", dob="2006-03-12", ref="r2"),
        ]
    )
    assert [r.status for r in results] == ["match", "not_found"]
    assert [r.ref for r in results] == ["r1", "r2"]
    assert all(r.available for r in results)


def test_client_single_verify(registry_client: TestClient) -> None:
    client = _client_against(registry_client)
    result = client.verify(RegistryRecord(apaar="987654321098", name="Aisha Fatima Khan", dob="2005-11-02"))
    assert result.status == "match"


def test_client_reports_source_unavailable_when_the_registry_is_down() -> None:
    """Nothing raises: an upload must not crash because the registry is offline."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = RegistryClient(
        base_url="http://127.0.0.1:1",
        api_key=API_KEY,
        timeout=0.05,
        transport=httpx.MockTransport(refuse),
        retries=1,
    )
    results = client.verify_batch(
        [RegistryRecord(apaar="123456781234", name="Rahul Sharma", dob="2006-03-12", ref="r1")]
    )
    assert len(results) == 1
    assert results[0].status == "source_unavailable"
    assert results[0].available is False
    assert results[0].apaar_masked == "XXXX-XXXX-1234"
    assert "did not respond" in (results[0].message or "")


def test_client_reports_source_unavailable_on_a_server_error() -> None:
    client = RegistryClient(
        base_url="http://registry.test",
        api_key=API_KEY,
        transport=httpx.MockTransport(lambda request: httpx.Response(500, json={"detail": "boom"})),
    )
    results = client.verify_batch([RegistryRecord(apaar="123456781234", ref="r1")])
    assert results[0].status == "source_unavailable"


def test_client_reports_source_unavailable_on_a_bad_api_key(registry_client: TestClient) -> None:
    client = _client_against(registry_client, api_key="wrong-key")
    results = client.verify_batch([RegistryRecord(apaar="123456781234", ref="r1")])
    assert results[0].status == "source_unavailable"


def test_client_health_when_down() -> None:
    client = RegistryClient(
        base_url="http://registry.test",
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("down", request=request))
        ),
    )
    assert client.health()["status"] == "unavailable"


def test_client_chunks_large_batches(registry_client: TestClient) -> None:
    """A 5,000-row upload must not send one 5,000-record request."""
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        records = json.loads(request.content)["records"]
        sizes.append(len(records))
        return httpx.Response(
            200,
            json={
                "checked_at": "2026-10-26T00:00:00Z",
                "count": len(records),
                "results": [
                    {"ref": r["ref"], "apaar_masked": "XXXX-XXXX-0000", "status": "not_found"}
                    for r in records
                ],
            },
        )

    client = RegistryClient(base_url="http://registry.test", transport=httpx.MockTransport(handler))
    records = [RegistryRecord(apaar=f"{i:012d}", ref=f"r{i}") for i in range(1200)]
    results = client.verify_batch(records)
    assert len(results) == 1200
    assert sizes == [500, 500, 200]
