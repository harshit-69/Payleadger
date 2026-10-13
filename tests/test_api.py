import os

DB_FILE = "test_payledger.db"
os.environ["DATABASE_URL"] = f"sqlite:///./{DB_FILE}"
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def make_user(email, password="password123"):
    client.post("/api/register", json={"email": email, "password": password})
    token = client.post("/api/login", json={"email": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_register_duplicate_and_bad_login():
    make_user("dup@test.com")
    assert client.post("/api/register", json={"email": "dup@test.com", "password": "password123"}).status_code == 409
    assert client.post("/api/login", json={"email": "dup@test.com", "password": "wrongpass1"}).status_code == 401


def test_requires_auth():
    assert client.get("/api/me").status_code in (401, 403)


def test_deposit_and_transfer():
    a, b = make_user("a@test.com"), make_user("b@test.com")
    client.post("/api/deposit", json={"amount_cents": 5000}, headers={**a, "Idempotency-Key": "d1"})
    r = client.post("/api/transfer", json={"to_email": "b@test.com", "amount_cents": 1200}, headers={**a, "Idempotency-Key": "t1"})
    assert r.status_code == 200
    assert client.get("/api/me", headers=a).json()["balance_cents"] == 3800
    assert client.get("/api/me", headers=b).json()["balance_cents"] == 1200


def test_insufficient_funds():
    c = make_user("c@test.com")
    make_user("d@test.com")
    r = client.post("/api/transfer", json={"to_email": "d@test.com", "amount_cents": 100}, headers={**c, "Idempotency-Key": "x1"})
    assert r.status_code == 422


def test_idempotency_applies_once():
    e = make_user("e@test.com")
    for _ in range(3):
        r = client.post("/api/deposit", json={"amount_cents": 700}, headers={**e, "Idempotency-Key": "same-key"})
        assert r.status_code == 200
    assert client.get("/api/me", headers=e).json()["balance_cents"] == 700
    assert len(client.get("/api/transactions", headers=e).json()) == 1
