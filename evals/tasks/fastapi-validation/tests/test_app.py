"""Existing tests for FastAPI app."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_create_user_ok():
    response = client.post(
        "/users/", json={"name": "Ada", "email": "ada@example.com", "age": 30}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Ada"
