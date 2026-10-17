"""Financing in the business's own currency: lender limits (set in USD) are converted, never compared raw."""
import pytest

from app import fx, models
from app.config import get_settings

PROFILE_FIELDS = ("name", "industry", "region", "foundedDate", "employees", "currency", "creditScore", "hasCollateral")


def set_currency(client, h, currency):
    profile = client.get("/api/business/profile", headers=h).json()
    body = {k: profile[k] for k in PROFILE_FIELDS} | {"currency": currency}
    r = client.put("/api/business/profile", json=body, headers=h)
    assert r.status_code == 200, r.text


def match(client, h, amount, purpose="equipment"):
    r = client.post("/api/financing/match", json={"amount": amount, "purpose": purpose}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_rates_and_formatting(monkeypatch):
    assert fx.rate("USD", "BDT") == 122.0 and fx.rate("BDT", "BDT") == 1.0
    assert fx.convert(1220, "BDT", "USD") == pytest.approx(10)
    assert fx.fmt(5_490_000, "BDT") == "BDT 5,490,000" and fx.fmt(-1500, "USD") == "-$1,500"
    with pytest.raises(fx.UnknownCurrency):
        fx.rate("USD", "XYZ")
    # FX_RATES overrides the built-in table.
    monkeypatch.setattr(get_settings(), "fx_rates", '{"BDT": 120, "jpy": 150}')
    fx.rates.cache_clear()
    try:
        assert fx.rate("USD", "BDT") == 120 and fx.rate("USD", "JPY") == 150
    finally:
        monkeypatch.undo()
        fx.rates.cache_clear()


def test_bdt_business_gets_converted_limits_and_bdt_wording(client):
    h = client.as_role("owner")
    usd = match(client, h, 45_000)
    assert usd["currency"] == "USD" and usd["fx"] == [] and usd["eligible"]

    set_currency(client, h, "BDT")
    bdt = match(client, h, 45_000)  # BDT 45,000 is about $370: below every lender's minimum
    assert bdt["currency"] == "BDT" and bdt["eligible"] == []
    assert bdt["fx"] == [{"from": "USD", "to": "BDT", "rate": 122.0}] and "1 USD = 122 BDT" in bdt["disclaimer"]
    reasons = [r for p in bdt["ineligible"] for r in p["ineligibleReasons"]]
    assert any(r.startswith("Minimum amount is BDT ") for r in reasons)
    assert not any("$" in r for r in reasons)
    with client.session() as s:
        smallest = min(p.MinAmount for p in s.query(models.FinProduct))
    assert min(p["amountRange"][0] for p in bdt["ineligible"]) == pytest.approx(smallest * 122)


def test_same_business_in_bdt_matches_the_same_products(client):
    """Scale revenue and the request by the rate: eligibility must be identical to the USD view."""
    h = client.as_role("owner")
    usd_ids = {e["productId"] for e in match(client, h, 45_000)["eligible"]}
    set_currency(client, h, "BDT")
    with client.session() as s:
        biz = s.get(models.SmeBusiness, 1)
        biz.AnnualRevenue *= 122
        s.commit()
    bdt = match(client, h, 45_000 * 122)
    assert {e["productId"] for e in bdt["eligible"]} == usd_ids
    top = bdt["eligible"][0]
    assert top["monthlyPayment"] > 100_000  # payments are in BDT, not dollars

    # Applying checks the amount against the converted limits and words the request in BDT.
    r = client.post("/api/approvals", json={
        "tool": "submit_loan_application", "rationale": "test",
        "params": {"productId": top["productId"], "amount": 45_000 * 122, "termMonths": top["termMonths"],
                   "purpose": "equipment"}}, headers=h)
    assert r.status_code in (200, 201), r.text
    assert "BDT 5,490,000" in r.json()["summary"]


def test_currency_without_a_rate_is_a_clear_error(client):
    h = client.as_role("owner")
    set_currency(client, h, "XYZ")
    r = client.post("/api/financing/match", json={"amount": 1000, "purpose": "equipment"}, headers=h)
    assert r.status_code == 422 and "XYZ" in r.json()["detail"]


# ---- approval limits and cash flow in the business currency ------------------------------------

def test_safety_limits_follow_the_currency():
    from app.actions import safety_limits
    usd, bdt = safety_limits("USD"), safety_limits("BDT")
    assert (usd.reauth, usd.payment_max, usd.daily_max) == (5_000, 10_000, 25_000)
    assert (bdt.reauth, bdt.payment_max, bdt.daily_max) == (610_000, 1_200_000, 3_000_000)  # rounded conversions
    assert safety_limits("XYZ").payment_max == 10_000  # no rate: the USD figures apply unchanged


def test_bdt_business_payment_limits_and_policy(client):
    h = client.as_role("owner")
    big = next(b for b in client.get("/api/ledger/bills?status=open", headers=h).json() if b["amount"] > 10_000)
    request = {"tool": "schedule_payment", "params": {"billId": big["id"], "payDate": big["dueDate"]}}
    assert client.post("/api/approvals", json=request, headers=h).status_code == 403  # over $10,000

    set_currency(client, h, "BDT")
    policy = client.get("/api/policy", headers=h).json()
    assert policy["currency"] == "BDT" and policy["schedulePaymentMax"] == 1_200_000 and policy["reauthThreshold"] == 610_000
    r = client.post("/api/approvals", json=request, headers=h)  # the same figure is small in taka
    assert r.status_code in (200, 201), r.text
    req = r.json()
    assert req["summary"].startswith(f"Pay {big['vendor']} BDT ") and req["requiresReauth"] is False
    done = client.post(f"/api/approvals/{req['id']}/approve", json={}, headers=h)  # no password needed below BDT 610,000
    assert done.status_code == 200 and done.json()["status"] == "executed", done.text
    assert "BDT" in done.json()["result"]["message"]


def test_bdt_cash_flow_scenarios_alerts_and_offline_answers(client):
    h = client.as_role("owner")
    set_currency(client, h, "BDT")
    r = client.post("/api/scenarios/run", json={"changes": [{"type": "new_hire", "monthlyCost": 150_000}]}, headers=h)
    assert r.status_code == 200, r.text  # was capped at 100,000 (a dollar-sized limit)
    body = r.json()
    assert body["changes"][0]["description"] == "New hire costing BDT 150,000/month"
    assert "BDT" in body["verdict"] and "$" not in body["verdict"]

    alerts = client.get("/api/alerts", headers=h).json()
    text = " ".join(f"{a['title']} {a['detail']} {a['suggestedAction']}" for a in alerts)
    assert "BDT" in text and "$" not in text

    sid = client.post("/api/chat/sessions", headers=h).json()["id"]
    answer = client.post(f"/api/chat/sessions/{sid}/messages?stream=false",
                         json={"content": "Will I run out of cash?"}, headers=h).json()
    assert "BDT" in answer["content"] and "$" not in answer["content"]
    assert answer["groundedness"]["unverified"] == []
