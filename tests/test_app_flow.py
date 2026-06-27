"""End-to-end account + device pairing + key management via the API."""
from fastapi.testclient import TestClient

from backend import repositories
from backend.main import app

client = TestClient(app)
DEVICE = "AA:BB:CC:00:11:22"


def _account_token() -> str:
    return client.post("/api/app/account").json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_account_creation_returns_token():
    body = client.post("/api/app/account").json()
    assert body["account_id"] and body["token"]


def test_pairing_binds_device_to_account():
    token = _account_token()
    client.get("/api/setup", headers={"ID": DEVICE})
    code = repositories.get_device(DEVICE).pairing_code

    res = client.post("/api/app/devices/pair", json={"pairing_code": code},
                      headers=_auth(token))
    assert res.status_code == 200
    assert res.json()["status"] == "paired"

    # The device now appears under the account.
    listing = client.get("/api/app/devices", headers=_auth(token)).json()
    assert [d["id"] for d in listing["devices"]] == [DEVICE]


def test_other_account_cannot_access_device():
    owner = _account_token()
    intruder = _account_token()
    client.get("/api/setup", headers={"ID": DEVICE})
    code = repositories.get_device(DEVICE).pairing_code
    client.post("/api/app/devices/pair", json={"pairing_code": code}, headers=_auth(owner))

    res = client.get(f"/api/app/devices/{DEVICE}", headers=_auth(intruder))
    assert res.status_code == 404


def test_key_lifecycle_and_required_flag():
    token = _account_token()
    acc_id = client.get("/api/app/account", headers=_auth(token)).json()["account_id"]

    # Default = platform.
    assert client.get("/api/app/account", headers=_auth(token)).json()["key_status"] == "platform"

    # Set own key → own.
    client.put("/api/app/account/key", json={"openai_api_key": "sk-user-supplied-key"},
               headers=_auth(token))
    assert client.get("/api/app/account", headers=_auth(token)).json()["key_status"] == "own"

    # Admin flips require-own-key; clearing is then blocked.
    client.post(f"/api/app/admin/accounts/{acc_id}/require-own-key",
                headers={"X-Admin-Token": "admin-test-token"})
    blocked = client.delete("/api/app/account/key", headers=_auth(token))
    assert blocked.status_code == 409


def test_unpaired_device_display_and_splash():
    client.get("/api/setup", headers={"ID": DEVICE})
    disp = client.get("/api/display", headers={"ID": DEVICE}).json()
    assert disp["refresh_rate"] == 300
    img = client.get(f"/media/current/{DEVICE}.png")
    assert img.status_code == 200 and img.content[:8].startswith(b"\x89PNG")
