#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'frontend/consumer/app.js').read_text(encoding='utf-8')
CSS=(ROOT/'frontend/consumer/styles.css').read_text(encoding='utf-8')
CONSUMER=(ROOT/'src/go_hotel/api/routes/consumer.py').read_text(encoding='utf-8')

checks={
    'hotel_search_surface': 'function showHotelSearch()' in APP and '查询酒店' in APP,
    'hotel_results_filters': 'GO 推荐' in APP and '价格 / 星级' in APP and '官方直连' in APP,
    'hotel_room_fact_productization': 'roomFacts(o' in APP and 'room_attributes' in CONSUMER and 'bed_configurations' in CONSUMER and 'occupancy' in CONSUMER,
    'official_benefits_surface': 'official_benefits' in APP and 'DirectValueOfferRow' in CONSUMER,
    'hotel_review_truth_warning': '未完成渠道认证时不会产生扣款成功或预订成功' in APP,
    'flight_search_surface': 'function showFlightSearch()' in APP and "'/v1/flights/search'" in APP,
    'flight_fare_surface': 'function renderFlightOffer' in APP and '托运行李' in APP and '改签' in APP and '退票' in APP,
    'flight_order_payment_readiness': "'/v1/flights/orders'" in APP and '/checkout' in APP and '创建待支付订单' in APP,
    'flight_no_fake_ticket_claim': '不表示已出票或已付款' in APP and '不代表真实航司生产出票或生产支付已启用' in APP and '外部航司/票务执行未通过认证时不会生成“出票成功”' in APP,
    'go_vi_tokens_reused': 'var(--navy)' in CSS and 'var(--coral)' in CSS,
    'competitor_brand_not_copied': all(x not in APP for x in ('金钻贵宾','优享会','携程积分','携程榜单')),
    'no_schema_change': not (ROOT/'alembic/versions/0112').exists(),
}
failed=[k for k,v in checks.items() if not v]
if failed:
    print('R8.2_RC17_8_CONSUMER_TRANSACTION_UX_GATE: BLOCK')
    print('failed=' + ','.join(failed))
    raise SystemExit(1)
print('R8.2_RC17_8_CONSUMER_TRANSACTION_UX_GATE: PASS')
for k in checks: print('PASS',k)
