from meridian import db
from meridian.worker import process_one


def test_authentication_workspace_and_role_boundaries(client, auth):
    assert client.get("/api/collections", headers={"X-Workspace": "atlas"}).status_code == 401
    headers = auth()
    assert client.get("/api/collections", headers={**headers, "X-Workspace": "boreal"}).status_code == 403
    assert client.get("/api/collections/atlas-board/documents", headers=headers).status_code == 403
    assert client.post("/api/exports", headers=headers, json={"collection_id": "atlas-board"}).status_code == 403
    assert client.post("/api/collections", headers=auth("viewer@atlas.test"), json={"name": "Unapproved"}).status_code == 403
    assert client.post("/api/auth/login", json={"email": "ada@atlas.test", "password": "wrong"}).status_code == 401


def test_document_lifecycle_with_optimistic_concurrency(client, auth):
    headers = auth()
    response = client.post("/api/collections/atlas-general/documents", headers=headers, json={"title": "Intake note", "body": "A searchable integration record."})
    assert response.status_code == 201
    document = response.json()
    updated = {"title": "Updated note", "body": "Revised integration record.", "expected_revision": 1}
    assert client.put(f"/api/documents/{document['id']}", headers=headers, json=updated).json()["revision"] == 2
    assert client.put(f"/api/documents/{document['id']}", headers=headers, json=updated).status_code == 409
    matches = client.post("/api/search", headers=headers, json={"query": "Revised integration"}).json()["results"]
    assert any(row["document_id"] == document["id"] for row in matches)
    assert client.delete(f"/api/documents/{document['id']}", headers=headers).status_code == 204
    assert client.get(f"/api/documents/{document['id']}", headers=headers).status_code == 404


def test_export_and_signed_download_binding(client, auth):
    headers = auth()
    job = client.post("/api/exports", headers=headers, json={"collection_id": "atlas-general", "format": "json"}).json()
    assert process_one()
    completed = client.get(f"/api/jobs/{job['id']}", headers=headers).json()
    assert completed["state"] == "succeeded"
    artifact_id = completed["result"]["artifact_id"]
    assert client.get(f"/api/artifacts/{artifact_id}", headers=headers).json()["documents"]
    url = client.post(f"/api/artifacts/{artifact_id}/share", headers=headers).json()["url"]
    assert client.get(url).status_code == 200
    assert client.get(url.replace("workspace=atlas", "workspace=boreal")).status_code == 403
    assert client.get(url.replace(artifact_id, "art_other")).status_code == 403
    assert client.get(url + "x").status_code == 403
    assert client.get(f"/api/artifacts/{artifact_id}", headers=auth("viewer@atlas.test")).status_code == 403


def test_workflow_approval_and_execution(client, auth):
    headers = auth()
    plan = {"name": "Team digest", "steps": [{"kind": "collect", "config": {"collection_id": "atlas-general"}}, {"kind": "publish", "config": {}}]}
    workflow = client.post("/api/workflows", headers=headers, json=plan).json()
    path = f"/api/workflows/{workflow['id']}"
    assert client.post(path + "/run", headers=headers, json={}).status_code == 409
    assert client.post(path + "/approve", headers=headers).status_code == 403
    assert client.post(path + "/approve", headers=auth("ada@atlas.test")).status_code == 200
    job = client.post(path + "/run", headers=headers, json={}).json()
    assert process_one()
    assert client.get(f"/api/jobs/{job['id']}", headers=headers).json()["state"] == "succeeded"


def test_cancelled_job_never_executes(client, auth):
    headers = auth()
    job = client.post("/api/exports", headers=headers, json={"collection_id": "atlas-general", "delay_seconds": 200}).json()
    assert client.post(f"/api/jobs/{job['id']}/cancel", headers=headers).status_code == 200
    db.execute("UPDATE jobs SET scheduled_at=0 WHERE id=?", (job["id"],))
    assert not process_one()
    assert client.get(f"/api/jobs/{job['id']}", headers=headers).json()["state"] == "cancelled"


def test_connector_input_policy_and_delivery_auth(client, auth):
    headers = auth()
    invalid = {"name": "bad-source", "collection_id": "atlas-general", "url": "http://vault:8093/catalog/continuity"}
    assert client.post("/api/sources", headers=headers, json=invalid).status_code == 422
    delivery = {"delivery_id": "delivery-123456", "title": "Supplier update", "body": "Supplier changes are scheduled for the next review."}
    preview = client.post("/api/sources/src_atlas_updates/preview-delivery", headers=headers, json=delivery).json()
    signed_headers = {**preview["headers"], "Content-Type": "application/json"}
    assert client.post(preview["url"], content=preview["body"], headers=signed_headers).status_code == 202
    assert client.post(preview["url"], content=preview["body"], headers=signed_headers).status_code == 409
    assert client.post(preview["url"], content=preview["body"] + " ", headers=signed_headers).status_code == 401


def test_conversation_is_private_and_logout_invalidates(client, auth):
    headers = auth()
    conversation = client.post("/api/conversations", headers=headers, json={"title": "Private research"}).json()
    assert client.get(f"/api/conversations/{conversation['id']}", headers=auth("ada@atlas.test")).status_code == 403
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/me", headers=headers).status_code == 401


def test_api_contract_and_ui(client):
    assert client.get("/").status_code == 200
    assert "Meridian" in client.get("/").text
    schema = client.get("/openapi.json").json()
    assert len(schema["paths"]) >= 30
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
