import pytest
from sqlalchemy import select
from test_baseline import register

from app.auth import hasher
from app.models import User


@pytest.mark.parametrize("username", ["Capital", "has space", "dots.here", "éclair", "ab", "a" * 33])
def test_invalid_username(context, username):
    client, _, _ = context
    assert (
        client.post(
            "/auth/register",
            json={"email": "owner@example.com", "username": username, "password": "Strong-local-password"},
        ).status_code
        == 422
    )


def test_account_rename_password_and_sessions(context):
    client, factory, _ = context
    register(client)
    assert client.get("/account").json()["username"] == "owner"
    assert client.patch("/account", json={"username": "new_user-23"}).json()["username"] == "new_user-23"
    assert (
        client.post(
            "/account/password", json={"current_password": "wrong", "new_password": "Changed-local-password"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/account/password",
            json={"current_password": "Strong-local-password", "new_password": "Changed-local-password"},
        ).status_code
        == 200
    )
    assert client.get("/account").json()["session_count"] == 1
    with factory() as db:
        user = db.scalar(select(User))
        assert hasher.verify("Changed-local-password", user.password_hash)
    assert client.post("/account/sessions/revoke").status_code == 200
    client.post("/auth/logout")
    assert (
        client.post(
            "/auth/login", json={"email": "owner@example.com", "password": "Strong-local-password"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login", json={"email": "owner@example.com", "password": "Changed-local-password"}
        ).status_code
        == 200
    )
    assert client.get("/auth/me").json()["username"] == "new_user-23"
    assert (
        client.post(
            "/auth/register",
            json={
                "email": "other@example.com",
                "username": "new_user-23",
                "password": "Strong-local-password",
            },
        ).status_code
        == 409
    )
