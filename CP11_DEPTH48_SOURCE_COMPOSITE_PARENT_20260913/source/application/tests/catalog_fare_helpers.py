from copy import deepcopy
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderRow, PrebookRow
from go_hotel.services import catalog_fare_snapshot as fare


def publish_for_order(order_id, **changes):
    with SessionLocal() as s:
        order=s.get(OrderRow,order_id)
        offer_id=s.get(PrebookRow,order.prebook_id).offer_id
        supplier=order.supplier_id
    current=fare.configured(offer_id,supplier)
    rules={**deepcopy(current['rules']),**changes}
    return fare.publish(offer_id,rules,'simulation://explicit-rule-change','fixture-supplier',supplier,current['version_id'])
