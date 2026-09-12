from tests.vertical_transaction_helpers import pay_and_confirm
def auth(client):
 r=client.post("/v1/consumer/auth/register",json={"email":"mobility@example.com","password":"StrongPass123!","display_name":"GO Mobility"}); assert r.status_code==200; t=client.post("/v1/mobile/auth/login",json={"email":"mobility@example.com","password":"StrongPass123!"}).json()["data"]; client.cookies.clear(); return {"Authorization":"Bearer "+t["access_token"]}
def test_ride_and_rental_golden_path(client):
 h=auth(client)
 s=client.post("/v1/mobility/rides/search",json={"pickup":"PVG","dropoff":"Shanghai Bund","pickup_at":"2026-09-01T10:00:00","currency":"CNY"});assert s.status_code==200
 o=client.post("/v1/mobility/rides/orders",headers=h,json={"offer_id":s.json()["data"]["items"][0]["offer_id"],"pickup":"PVG","dropoff":"Shanghai Bund","pickup_at":"2026-09-01T10:00:00","currency":"CNY","flight_no":"MU510"});assert o.status_code==200;oid=o.json()["data"]["order_id"];assert o.json()['data']['status']=='PAYMENT_PENDING';pay_and_confirm(client,h,'RIDE_ORDER',oid,'RIDE-'+oid[-6:])
 assert client.post(f"/v1/mobility/orders/{oid}/modify",headers=h,json={"new_time":"2026-09-01T11:00:00"}).status_code==200
 assert client.post(f"/v1/mobility/orders/{oid}/cancel",headers=h).json()["data"]["status"]=="REFUND_COMPLETED"
 s=client.post("/v1/mobility/rentals/search",json={"pickup_location":"NRT","return_location":"NRT","pickup_at":"2026-09-02T09:00:00","return_at":"2026-09-05T09:00:00","currency":"CNY"});assert s.status_code==200
 x=s.json()["data"]["items"][0];assert "insurance" in x and "mileage" in x and "deposit_minor" in x
 o=client.post("/v1/mobility/rentals/orders",headers=h,json={"offer_id":x["offer_id"],"pickup_location":"NRT","return_location":"NRT","pickup_at":"2026-09-02T09:00:00","return_at":"2026-09-05T09:00:00","currency":"CNY"});assert o.status_code==200;rid=o.json()['data']['order_id'];pay_and_confirm(client,h,'RENTAL_ORDER',rid,'RENT-'+rid[-6:])
