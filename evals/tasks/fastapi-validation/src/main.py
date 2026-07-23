"""FastAPI app seed."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI()


@app.post("/users/")
def create_user(name: str, email: str, age: int) -> dict:
    """Create a user. Currently lacks input validation."""
    return {"id": 1, "name": name, "email": email, "age": age}
