def _seed_prebook(client):
    search = client.post("/v1/search/hotels", json={
        "destination": {"city_code": "TYO"},
        "stay": {"check_in": "2026-09-01", "check_out": "2026-09-05"},
        "currency": "CNY"
    }).json()
    offer_id = search["data"]["hotels"][0]["best_offer"]["offer_id"]
    return client.post(f"/v1/offers/{offer_id}/prebook", json={"currency": "CNY"}).json()["data"]["prebook_id"]


def test_create_order_idempotent(client):
    pb = _seed_prebook(client)
    headers = {"Idempotency-Key": "same-key"}
    body = {"prebook_id": pb, "account_id": "acct_demo"}
    a = client.post("/v1/orders", headers=headers, json=body)
    b = client.post("/v1/orders", headers=headers, json=body)
    assert a.status_code == 200
    assert b.status_code == 200
    assert a.json() == b.json()


def test_idempotency_conflict(client):
    pb = _seed_prebook(client)
    headers = {"Idempotency-Key": "same-key"}
    a = client.post("/v1/orders", headers=headers, json={"prebook_id": pb, "account_id": "acct_a"})
    assert a.status_code == 200
    b = client.post("/v1/orders", headers=headers, json={"prebook_id": pb, "account_id": "acct_b"})
    assert b.status_code == 409
    assert b.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
