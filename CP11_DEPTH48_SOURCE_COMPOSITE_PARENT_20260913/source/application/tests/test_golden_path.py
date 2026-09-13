def test_search_prebook_pay_book_confirm(client):
    search = client.post("/v1/search/hotels", json={
        "destination": {"city_code": "TYO"},
        "stay": {"check_in": "2026-09-01", "check_out": "2026-09-05"},
        "occupancy": {"rooms": 1, "adults": 2, "children": 0},
        "currency": "CNY"
    })
    assert search.status_code == 200
    offer = search.json()["data"]["hotels"][0]["best_offer"]

    pb = client.post(f"/v1/offers/{offer['offer_id']}/prebook", json={"currency": "CNY"})
    assert pb.status_code == 200
    prebook_id = pb.json()["data"]["prebook_id"]

    order_res = client.post("/v1/orders", headers={"Idempotency-Key": "idem-order-1"}, json={
        "prebook_id": prebook_id,
        "account_id": "acct_demo"
    })
    assert order_res.status_code == 200
    order = order_res.json()["data"]
    assert order["status"] == "PAYMENT_PENDING"

    pay = client.post(f"/v1/orders/{order['order_id']}/payments", headers={"Idempotency-Key": "idem-pay-1"}, json={
        "payment_method_token": "pm_success",
        "amount_minor": order["total_amount_minor"],
        "currency": "CNY"
    })
    assert pay.status_code == 200
    assert pay.json()["data"]["status"] == "AUTHORIZED"

    confirm = client.post(f"/internal/v1/orders/{order['order_id']}/confirm")
    assert confirm.status_code == 200
    assert confirm.json()["data"]["status"] == "CONFIRMED"
    assert confirm.json()["data"]["supplier_confirmation_no"].startswith("MOCK-")

    events = client.get(f"/internal/v1/orders/{order['order_id']}/events").json()["data"]
    types = [e["event_type"] for e in events]
    assert types == [
        "ORDER_CREATED",
        "ORDER_FARE_RULE_ACCEPTED",
        "PAYMENT_AUTHORIZED",
        "SUPPLIER_BOOKING_STARTED",
        "SUPPLIER_CONFIRMATION_RECEIVED",
        "PAYMENT_CAPTURED",
        "ORDER_CONFIRMED",
    ]
