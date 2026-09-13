from tests.attraction_fixtures import quoted_attraction
from go_hotel.attractions.service import attraction_service
from tests.vertical_transaction_helpers import pay_and_confirm
def auth(client):
 r=client.post("/v1/consumer/auth/register",json={"email":"attr@example.com","password":"StrongPass123!","display_name":"GO Attractions"});assert r.status_code==200
 t=client.post("/v1/mobile/auth/login",json={"email":"attr@example.com","password":"StrongPass123!"}).json()["data"];client.cookies.clear();return {"Authorization":"Bearer "+t["access_token"]}
def test_attraction_golden_path(client):
 h=auth(client)
 s=client.post("/v1/attractions/search",json={"destination":"东京","visit_date":"2026-09-03"});assert s.status_code==200;items=s.json()["data"]["items"];assert len(items)>=3;assert "eligibility" in items[0] and "inventory_units" in items[0]
 off=items[0];p=client.post("/v1/attractions/prebook",json={"offer_id":off["offer_id"],"visit_date":"2026-09-03","quantity":2});assert p.status_code==200;assert p.json()["data"]["inventory_confirmed"] is True
 o=client.post("/v1/attractions/orders",headers=h,json={"prebook_id":p.json()["data"]["prebook_id"],"offer_id":off["offer_id"],"visit_date":"2026-09-03","quantity":2,"attendees":[{"name":"A"},{"name":"B"}]});assert o.status_code==200;d=o.json()["data"];assert d["status"]=="PAYMENT_PENDING" and d["voucher_code"] is None;pay_and_confirm(client,h,"ATTRACTION_ORDER",d["order_id"],"ATTR-"+d["order_id"][-6:],voucher_code="VCHR-"+d["order_id"][-6:]);d=client.get(f"/v1/attractions/orders/{d['order_id']}",headers=h).json()["data"];assert d["status"]=="CONFIRMED" and d["voucher_code"]
 oid=d["order_id"];q=client.post(f"/v1/attractions/orders/{oid}/change-quote",headers=h,json={"new_visit_date":"2026-09-04","new_session_time":"17:00"});assert q.status_code==200
 qid=q.json()["data"]["quote_id"];e=client.post(f"/v1/attractions/orders/{oid}/execute-change/{qid}",headers=h);assert e.status_code==200 and e.json()["data"]["status"]=="UNKNOWN_EXTERNAL_STATE" and e.json()["data"]["voucher_code"] is None
 rec=attraction_service.admin_external_state(oid,"CONFIRMED","supplier-change-proof","ops","ATTR-REISSUED","VCHR-REISSUED");assert rec["visit_date"]=="2026-09-04" and rec["voucher_code"]=="VCHR-REISSUED"
 rq=client.get(f"/v1/attractions/orders/{oid}/refund-quote",headers=h);assert rq.status_code==200 and rq.json()["data"]["refund_amount_minor"]>0
 rr=client.post(f"/v1/attractions/orders/{oid}/refund",headers=h);assert rr.status_code==200 and rr.json()["data"]["status"]=="REFUND_COMPLETED"
def test_non_refundable_experience(client):
 h=auth(client);o=client.post("/v1/attractions/orders",headers=h,json=quoted_attraction(client,{"offer_id":"teamlab_planets","visit_date":"2026-09-03","quantity":1})).json()["data"];pay_and_confirm(client,h,"ATTRACTION_ORDER",o["order_id"],"ATTR-"+o["order_id"][-6:],voucher_code="VCHR-"+o["order_id"][-6:]);rq=client.get(f"/v1/attractions/orders/{o['order_id']}/refund-quote",headers=h).json()["data"];assert rq["refund_amount_minor"]==0 and rq["refundable"] is False
