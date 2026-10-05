from tests.vertical_transaction_helpers import confirm_existing_fulfillment


def auth(client, email="rail-display@example.com"):
    response = client.post(
        "/v1/consumer/auth/register",
        json={
            "email": email,
            "password": "StrongPass123!",
            "display_name": "Rail Traveler",
        },
    )
    assert response.status_code == 200, response.text
    token = client.post(
        "/v1/mobile/auth/login",
        json={"email": email, "password": "StrongPass123!"},
    ).json()["data"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token['access_token']}"}


def create_ticketed(client, headers):
    search = client.post(
        "/v1/rail/search",
        json={
            "origin_station": "SHA",
            "destination_station": "HZH",
            "travel_date": "2026-09-01",
            "currency": "CNY",
        },
    )
    assert search.status_code == 200, search.text
    offer_id = search.json()["data"]["items"][0]["offer_id"]
    prebook = client.post(f"/v1/rail/offers/{offer_id}/prebook")
    assert prebook.status_code == 200, prebook.text
    order = client.post(
        "/v1/rail/orders",
        headers=headers,
        json={
            "prebook_id": prebook.json()["data"]["prebook_id"],
            "passengers": [{"full_name": "CHEN TEST", "type": "ADT"}],
        },
    )
    assert order.status_code == 200, order.text
    order_id = order.json()["data"]["order_id"]
    checkout = client.post(
        f"/v1/rail/orders/{order_id}/checkout",
        headers=headers,
        json={"payment_method_id": "pm_test_token"},
    )
    assert checkout.status_code == 200, checkout.text
    booking_reference = "RAIL-" + order_id[-6:]
    ticket_numbers = ["R-" + order_id[-8:]]
    confirm_existing_fulfillment(client, order_id, booking_reference, ticket_numbers)
    return order_id, booking_reference, ticket_numbers


def test_rail_order_keeps_issued_facts_while_change_result_is_unknown(client):
    headers = auth(client)
    order_id, booking_reference, ticket_numbers = create_ticketed(client, headers)

    quote = client.post(
        f"/v1/rail/orders/{order_id}/change-quote",
        headers=headers,
        json={"new_travel_date": "2026-09-03", "new_seat_class": "SECOND_CLASS"},
    )
    assert quote.status_code == 200, quote.text
    execute = client.post(
        f"/v1/rail/orders/{order_id}/execute-change/{quote.json()['data']['quote_id']}",
        headers=headers,
    )
    assert execute.status_code == 200, execute.text
    pending = execute.json()["data"]

    assert pending["status"] == "UNKNOWN_EXTERNAL_STATE"
    assert pending["booking_reference"] == booking_reference
    assert pending["ticket_numbers"] == ticket_numbers

    trips = client.get("/v1/consumer/trips", headers=headers)
    assert trips.status_code == 200, trips.text
    rail_trip = next(
        item
        for item in trips.json()["data"]["items"]
        if item["vertical"] == "RAIL" and item["order_id"] == order_id
    )
    assert rail_trip["status"] == "UNKNOWN_EXTERNAL_STATE"
    assert rail_trip["booking_reference"] == booking_reference
    assert rail_trip["ticket_numbers"] == ticket_numbers
