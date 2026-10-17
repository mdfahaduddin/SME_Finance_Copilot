"""Business profile: what Settings sends, what the API accepts, who may change it."""
from tests.test_import import new_business

EDITABLE = ("name", "industry", "region", "foundedDate", "employees", "currency", "creditScore", "hasCollateral")


def editable(profile: dict) -> dict:
    """The body the Settings page sends: only the editable fields."""
    return {k: profile[k] for k in EDITABLE}


def test_owner_updates_profile(client):
    new_business(client)
    h = {"X-CSRF-Token": client.cookies.get("sme_csrf")}
    profile = client.get("/api/business/profile").json()
    body = {**editable(profile), "name": "Blue Fern Studio Ltd", "creditScore": 712, "hasCollateral": True}
    r = client.put("/api/business/profile", json=body, headers=h)
    assert r.status_code == 200, r.text
    saved = client.get("/api/business/profile").json()
    assert (saved["name"], saved["creditScore"], saved["hasCollateral"]) == ("Blue Fern Studio Ltd", 712, True)


def test_read_only_fields_are_rejected(client):
    """Sending the GET response back unchanged includes read-only fields; the API must refuse, not ignore them."""
    new_business(client)
    h = {"X-CSRF-Token": client.cookies.get("sme_csrf")}
    profile = client.get("/api/business/profile").json()
    r = client.put("/api/business/profile", json={**editable(profile), "onboardingStatus": "complete"}, headers=h)
    assert r.status_code == 422


def test_future_founded_date_is_rejected(client):
    new_business(client)
    h = {"X-CSRF-Token": client.cookies.get("sme_csrf")}
    body = {**editable(client.get("/api/business/profile").json()), "foundedDate": "2999-01-01"}
    assert client.put("/api/business/profile", json=body, headers=h).status_code == 422


def test_only_owner_can_edit(client):
    h = client.as_role("accountant")
    body = editable(client.get("/api/business/profile", headers=h).json())
    assert client.put("/api/business/profile", json=body, headers=h).status_code == 403
