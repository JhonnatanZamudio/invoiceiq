import pytest

from conftest import signup, upload
from invoiceiq.config import Settings
from invoiceiq.main import create_app


def test_refuses_default_secret_outside_sqlite():
    with pytest.raises(RuntimeError, match="INVOICEIQ_SECRET_KEY"):
        create_app(Settings(database_url="postgresql+psycopg://u:p@db/invoiceiq"))


def test_signup_login_and_me(client):
    signup(client, "ana@empresa-a.test", "Empresa A")
    res = client.post(
        "/api/auth/login", json={"email": "ANA@empresa-a.test", "password": "password123"}
    )
    assert res.status_code == 200
    me = client.get("/api/me", headers={"Authorization": f"Bearer {res.json()['access_token']}"})
    assert me.json()["role"] == "owner" and me.json()["organization_name"] == "Empresa A"


def test_bad_credentials_and_tokens_are_rejected(client):
    signup(client, "ana@empresa-a.test")
    bad = client.post("/api/auth/login", json={"email": "ana@empresa-a.test", "password": "nope"})
    assert bad.status_code == 401
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer forged"}).status_code == 401
    dup = client.post(
        "/api/auth/signup",
        json={
            "email": "ana@empresa-a.test",
            "password": "password123",
            "organization_name": "Otra",
        },
    )
    assert dup.status_code == 409


def test_passwords_are_hashed(client):
    signup(client, "ana@empresa-a.test")
    from invoiceiq.models import User

    with client.app.state.sessionmaker() as db:
        user = db.query(User).one()
        assert user.password_hash.startswith("$2") and "password123" not in user.password_hash


def test_only_owners_can_add_members(client):
    owner = signup(client, "ana@empresa-a.test", "Empresa A")
    res = client.post(
        "/api/users",
        headers=owner,
        json={"email": "luis@empresa-a.test", "password": "password123"},
    )
    assert res.status_code == 201 and res.json()["role"] == "member"
    login = client.post(
        "/api/auth/login", json={"email": "luis@empresa-a.test", "password": "password123"}
    )
    member = {"Authorization": f"Bearer {login.json()['access_token']}"}
    denied = client.post(
        "/api/users", headers=member, json={"email": "x@empresa-a.test", "password": "password123"}
    )
    assert denied.status_code == 403


def test_user_cannot_access_another_orgs_invoices(client, samples):
    org_a = signup(client, "ana@empresa-a.test", "Empresa A")
    org_b = signup(client, "bruno@empresa-b.test", "Empresa B")
    invoice_id = upload(client, org_a, samples / "fe_andina_1023.pdf").json()["id"]

    assert client.get(f"/api/invoices/{invoice_id}", headers=org_a).status_code == 200
    assert client.get("/api/invoices", headers=org_b).json() == []
    for method, path in [("get", ""), ("get", "/file"), ("post", "/approve")]:
        res = getattr(client, method)(f"/api/invoices/{invoice_id}{path}", headers=org_b)
        assert res.status_code == 404, path
    patch = client.patch(
        f"/api/invoices/{invoice_id}/fields", headers=org_b, json={"fields": {"total": "1"}}
    )
    assert patch.status_code == 404
    export = client.get("/api/invoices/export?format=csv", headers=org_b)
    assert export.text.strip().count("\n") == 0  # header row only


def test_duplicate_detection_is_per_tenant(client, samples):
    org_a = signup(client, "ana@empresa-a.test", "Empresa A")
    org_b = signup(client, "bruno@empresa-b.test", "Empresa B")
    upload(client, org_a, samples / "fv_tecno_0458.pdf")
    # Same supplier invoice in another tenant is not a duplicate.
    other = upload(client, org_b, samples / "fv_tecno_0458_dup.pdf").json()
    assert other["status"] == "approved"
