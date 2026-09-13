def test_payment_decline_does_not_confirm_order(client):
    search = client.post("/v1/search/hotels", json={
        "destination": {"city_code": "TYO"},
        "stay": {"check_in": "2026-09-01", "check_out": "2026-09-05"},
        "currency": "CNY"
    }).json()
    offer_id = search["data"]["hotels"][0]["best_offer"]["offer_id"]
    pb = client.post(f"/v1/offers/{offer_id}/prebook", json={"currency": "CNY"}).json()["data"]
    order = client.post("/v1/orders", json={"prebook_id": pb["prebook_id"], "account_id": "acct_demo"}).json()["data"]
    pay = client.post(f"/v1/orders/{order['order_id']}/payments", json={
        "payment_method_token": "pm_decline",
        "amount_minor": order["total_amount_minor"],
        "currency": "CNY"
    })
    assert pay.status_code == 422
    current = client.get(f"/v1/orders/{order['order_id']}").json()["data"]
    assert current["status"] == "PAYMENT_PENDING"

def test_declined_payment_can_retry_with_new_external_operation(client):
    search = client.post("/v1/search/hotels", json={
        "destination": {"city_code": "TYO"},
        "stay": {"check_in": "2026-09-01", "check_out": "2026-09-05"},
        "currency": "CNY"
    }).json()
    offer_id = search["data"]["hotels"][0]["best_offer"]["offer_id"]
    pb = client.post(f"/v1/offers/{offer_id}/prebook", json={"currency": "CNY"}).json()["data"]
    order = client.post("/v1/orders", json={"prebook_id": pb["prebook_id"], "account_id": "acct_retry"}).json()["data"]
    first = client.post(f"/v1/orders/{order['order_id']}/payments", json={"payment_method_token":"pm_decline","amount_minor":order["total_amount_minor"],"currency":"CNY"})
    assert first.status_code == 422
    second = client.post(f"/v1/orders/{order['order_id']}/payments", json={"payment_method_token":"pm_success","amount_minor":order["total_amount_minor"],"currency":"CNY"})
    assert second.status_code == 200
    assert second.json()["data"]["status"] == "AUTHORIZED"
