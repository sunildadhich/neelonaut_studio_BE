import os
os.environ["DATABASE_URL"] = "sqlite:///./test-studio.db"
os.environ["SECRET_KEY"] = "test-secret"

from fastapi.testclient import TestClient
from app.main import app


def test_private_document_isolation():
    with TestClient(app) as client:
        first = client.post("/api/v1/auth/signup", json={"email": "a@example.com", "username": "alice", "password": "a-secure-password"})
        assert first.status_code == 201
        workspace = client.post("/api/v1/workspaces", json={"name": "Alice"}).json()
        document = client.post("/api/v1/documents", json={"workspace_id": workspace["id"], "title": "Private", "content": {"blocks": []}})
        assert document.status_code == 201
        client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": client.cookies.get("studio_csrf")})
        second = client.post("/api/v1/auth/signup", json={"email": "b@example.com", "username": "bob", "password": "b-secure-password"})
        assert second.status_code == 201
        assert client.get(f"/api/v1/documents/{document.json()['id']}").status_code == 404


def test_document_version_conflict():
    with TestClient(app) as client:
        client.post("/api/v1/auth/signup", json={"email": "c@example.com", "username": "carol", "password": "c-secure-password"})
        workspace = client.post("/api/v1/workspaces", json={"name": "Carol"}).json()
        document = client.post("/api/v1/documents", json={"workspace_id": workspace["id"], "title": "Draft"}).json()
        csrf = client.cookies.get("studio_csrf")
        response = client.patch(f"/api/v1/documents/{document['id']}", headers={"X-CSRF-Token": csrf}, json={"expected_version": 99, "title": "Conflict"})
        assert response.status_code == 409
