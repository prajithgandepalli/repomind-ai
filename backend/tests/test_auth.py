import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import mongomock
import pytest
from fastapi.testclient import TestClient

import main
from auth.security import COOKIE
from auth.config import Settings

DATA = {"username": "River", "email": "River@Example.com", "password": "a sufficiently long password"}
CREDS = {key: DATA[key] for key in ("email", "password")}
PUBLIC = {"username": "River", "email": "river@example.com"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", secrets.token_hex(48))
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setattr(main, "MongoClient", mongomock.MongoClient)
    with TestClient(main.app, base_url="https://testserver", headers={"X-RepoMind-CSRF": "1"}) as api:
        yield api


def test_registration_login_logout(client):
    register = client.post("/api/auth/register", json=DATA)
    assert register.status_code == 201 and register.json() == PUBLIC
    stored = main.app.state.accounts.users.find_one()
    assert "password" not in stored and bcrypt.checkpw(DATA["password"].encode(), stored["password_hash"])
    assert client.post("/api/auth/register", json={**DATA, "email": PUBLIC["email"]}).status_code == 409
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={**CREDS, "password": "incorrect"}).status_code == 401
    login = client.post("/api/auth/login", json=CREDS)
    assert login.json() == PUBLIC
    for attr in ("httponly", "secure", "samesite=strict", "path=/api"):
        assert attr in login.headers["set-cookie"].lower()
    token = client.cookies.get(COOKIE)
    assert client.get("/api/auth/me?user_id=someone_else").json() == PUBLIC
    assert client.post("/api/auth/logout").status_code == 204
    assert COOKIE not in client.cookies
    client.cookies.set(COOKIE, token)
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("change", [
    {"username": "x"}, {"email": "invalid"}, {"password": "tiny"},
    {"password": "é" * 37}, {"owner": "someone_else"}
])
def test_validation(client, change):
    result = client.post("/api/auth/register", json={**DATA, **change})
    assert result.status_code == 422
    assert "input" not in result.text and DATA["password"] not in result.text


def test_bad_and_expired_tokens(client):
    client.post("/api/auth/register", json=DATA)
    client.post("/api/auth/login", json=CREDS)
    secret = main.app.state.settings.secret
    claims = jwt.decode(client.cookies.get(COOKIE), secret, algorithms=["HS256"])
    client.cookies.clear()
    for token in ["malformed", jwt.encode(claims, secrets.token_hex(48)),
                  jwt.encode({**claims, "exp": datetime.now(timezone.utc)-timedelta(seconds=2)}, secret)]:
        client.cookies.set(COOKIE, token)
        assert client.get("/api/auth/me").status_code == 401


def test_csrf(client):
    client.headers.pop("X-RepoMind-CSRF")
    for path in ("register", "login", "logout"):
        assert client.post("/api/auth/" + path, json=DATA).status_code == 403


def test_secret_required(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        Settings.load()

