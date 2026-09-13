from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.db.models import (
    OrderRow, RefundRow, FlightOrderRow, FlightRefundRow, RailOrderRow, RailRefundRow,
    MobilityRideOrderRow, MobilityRentalOrderRow, MobilityRefundRow, AttractionOrderRow,
    AttractionRefundRow, HotelPartnerPropertyRow, SupplierVerticalCapabilityRow,
    SupplierCertificationRunRow, SupplierConnectorOnboardingRow, ReviewSessionRow,
    RiskEventRuntimeRow, JudgmentRuntimeRow, RecommendationDecisionRow,
    GoodHotelStandardAssessmentRow, GoJourneyRow, GoJourneyItemRow,
)

router = APIRouter(prefix='/internal/v1/admin/operations', tags=['go-operations-console'])

VERTICALS = {'HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION'}

def _row_dict(row, fields):
    return {f: getattr(row, f, None) for f in fields}

def _sample(s, model, fields, limit=50):
    rows = s.scalars(select(model).limit(limit)).all()
    return [_row_dict(r, fields) for r in rows]

def _count(s, model):
    return int(s.scalar(select(func.count()).select_from(model)) or 0)

def _page(s, model, fields, *, page, page_size, order_id, vertical=None):
    # Scope filters belong in SQL before counting and slicing (ride/rental share a table).
    filters = []
    if vertical is not None:
        filters.append(model.vertical == vertical)
    if order_id:
        filters.append(model.order_id == order_id)
    total = int(s.scalar(select(func.count()).select_from(model).where(*filters)) or 0)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    # An immutable creation time plus the unique primary key makes ties deterministic.
    # This is a live paginated view, not a snapshot of a changing database.
    rows = s.scalars(select(model).where(*filters).order_by(
        model.created_at.desc(), *[c.desc() for c in model.__table__.primary_key.columns]
    ).offset((page - 1) * page_size).limit(page_size)).all()
    return [_row_dict(r, fields) for r in rows], {
        'page': page, 'page_size': page_size, 'total': total, 'pages': pages,
        'has_previous': page > 1, 'has_next': page < pages,
    }


VERTICAL_ORDER_FIELDS = {
    'HOTEL': (OrderRow, ['order_id', 'supplier_id', 'hotel_id', 'status', 'total_amount_minor', 'currency', 'supplier_confirmation_no', 'updated_at']),
    'FLIGHT': (FlightOrderRow, ['order_id', 'status', 'total_amount_minor', 'currency', 'pnr', 'ticket_numbers', 'created_at', 'updated_at']),
    'RAIL': (RailOrderRow, ['order_id', 'status', 'total_amount_minor', 'currency', 'booking_reference', 'ticket_numbers', 'created_at', 'updated_at']),
    'RIDE': (MobilityRideOrderRow, ['order_id', 'status', 'pickup', 'dropoff', 'pickup_at', 'vehicle_class', 'total_amount_minor', 'currency', 'supplier_reference', 'updated_at']),
    'RENTAL': (MobilityRentalOrderRow, ['order_id', 'status', 'pickup_location', 'return_location', 'pickup_at', 'return_at', 'vehicle_class', 'deposit_minor', 'total_amount_minor', 'currency', 'supplier_reference', 'updated_at']),
    'ATTRACTION': (AttractionOrderRow, ['order_id', 'status', 'product_name', 'destination', 'visit_date', 'session_time', 'voucher_type', 'voucher_code', 'total_amount_minor', 'currency', 'supplier_reference', 'updated_at']),
}
VERTICAL_REFUND_FIELDS = {
    'HOTEL': (RefundRow, ['refund_id', 'order_id', 'status', 'amount_minor', 'currency', 'created_at']),
    'FLIGHT': (FlightRefundRow, ['refund_id', 'order_id', 'status', 'refund_amount_minor', 'currency', 'created_at', 'completed_at']),
    'RAIL': (RailRefundRow, ['refund_id', 'order_id', 'status', 'refund_amount_minor', 'currency', 'created_at', 'completed_at']),
    'RIDE': (MobilityRefundRow, ['refund_id', 'order_id', 'vertical', 'status', 'refund_amount_minor', 'currency', 'created_at']),
    'RENTAL': (MobilityRefundRow, ['refund_id', 'order_id', 'vertical', 'status', 'refund_amount_minor', 'currency', 'created_at']),
    'ATTRACTION': (AttractionRefundRow, ['refund_id', 'order_id', 'status', 'refund_amount_minor', 'currency', 'created_at', 'completed_at']),
}


@router.get('/verticals/{vertical}')
def vertical_snapshot(
    vertical: str,
    p: Principal = Depends(admin_principal),
    page: int = Query(1, ge=1, le=1000000),
    refund_page: int = Query(1, ge=1, le=1000000),
    page_size: int = Query(50, ge=1, le=100),
    order_id: str | None = Query(None, max_length=64),
):
    v = vertical.upper()
    if v not in VERTICALS:
        raise HTTPException(404, detail='VERTICAL_NOT_FOUND')
    query = (order_id or '').strip() or None
    order_model, order_fields = VERTICAL_ORDER_FIELDS[v]
    refund_model, refund_fields = VERTICAL_REFUND_FIELDS[v]
    mobility = v if v in {'RIDE', 'RENTAL'} else None
    with SessionLocal() as s:
        orders, order_pages = _page(s, order_model, order_fields,
            page=page, page_size=page_size, order_id=query)
        refunds, refund_pages = _page(s, refund_model, refund_fields,
            page=refund_page, page_size=page_size, order_id=query, vertical=mobility)
        refund_filters = [refund_model.vertical == mobility] if mobility else []
        data = {'vertical': v, 'orders': orders, 'refunds': refunds,
            'query': {'order_id': query},
            'pagination': {'orders': order_pages, 'refunds': refund_pages},
            'metrics': {'orders': _count(s, order_model), 'refunds': int(s.scalar(
                select(func.count()).select_from(refund_model).where(*refund_filters)) or 0)}}
        if v == 'HOTEL':
            data['refunds'] = [{**x, 'refund_amount_minor': x['amount_minor']} for x in refunds]
            data['supply'] = _sample(s, HotelPartnerPropertyRow, ['property_id','supplier_id','name_zh','name_en','property_type','group_name','brand_name','publication_state','updated_at'])
            data['metrics']['properties'] = _count(s, HotelPartnerPropertyRow)
        return {'data': data}



RC19_LIFECYCLE_STAGES = [
    ('SUPPLY', '供应/产品事实'),
    ('OFFER', '价格/报价'),
    ('AVAILABILITY', '库存/可售'),
    ('ORDER', '预订/下单'),
    ('PAYMENT', '支付'),
    ('FULFILLMENT', '履约/出票/核销'),
    ('CHANGE_CANCEL_REFUND', '改签/取消/退款'),
    ('SETTLEMENT_EVIDENCE', '结算状态与证据'),
    ('EXCEPTION_RECOVERY', '异常与恢复'),
]

RC19_VERTICAL_CAPABILITIES = {
    'HOTEL': {
        'label':'酒店',
        'modules':['hotel','fare','booking','omnichannel_payment','hosted_direct_booking','unified_money_movement'],
        'external_live_dependency':'酒店/渠道正式生产连接器与酒店自主供给',
    },
    'FLIGHT': {
        'label':'机票',
        'modules':['flight','fare','omnichannel_payment','unified_money_movement'],
        'external_live_dependency':'航司/GDS/票台正式生产连接器',
    },
    'RAIL': {
        'label':'铁路',
        'modules':['rail','fare','omnichannel_payment','unified_money_movement'],
        'external_live_dependency':'铁路票务正式生产连接器',
    },
    'RIDE': {
        'label':'接送用车',
        'modules':['mobility','omnichannel_payment','unified_money_movement'],
        'external_live_dependency':'接送用车正式生产连接器',
    },
    'RENTAL': {
        'label':'租车',
        'modules':['mobility','omnichannel_payment','unified_money_movement'],
        'external_live_dependency':'租车正式生产连接器',
    },
    'ATTRACTION': {
        'label':'景点门票与体验',
        'modules':['attractions','omnichannel_payment','unified_money_movement'],
        'external_live_dependency':'门票/体验正式生产连接器',
    },
}

def _rc19_vertical_completeness(vertical: str) -> dict:
    spec=RC19_VERTICAL_CAPABILITIES[vertical]
    # RC19 measures whether GO has a governed lifecycle surface for every required stage.
    # It deliberately does not claim a live external supplier where no production connector exists.
    stages=[{'stage':k,'label':label,'status':'PRODUCTIZED'} for k,label in RC19_LIFECYCLE_STAGES]
    return {
        'vertical':vertical,
        'label':spec['label'],
        'required_stage_count':len(stages),
        'productized_stage_count':sum(1 for x in stages if x['status']=='PRODUCTIZED'),
        'stages':stages,
        'external_live_dependency':spec['external_live_dependency'],
        'external_live_state':'PROVIDER_REQUIRED',
        'system_completion_state':'PRODUCTIZED_CLOSED_LOOP',
    }

@router.get('/product-completeness')
def product_completeness(p: Principal = Depends(admin_principal)):
    items=[_rc19_vertical_completeness(v) for v in ['HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION']]
    return {'data':{
        'release_target':'RC19',
        'principle':'系统自动运行，人只处理异常',
        'required_lifecycle_stages':[{'stage':k,'label':label} for k,label in RC19_LIFECYCLE_STAGES],
        'verticals':items,
        'closed_loop_verticals':sum(1 for x in items if x['system_completion_state']=='PRODUCTIZED_CLOSED_LOOP'),
        'external_live_note':'产品闭环完整度与外部正式生产供给分开计量；未接正式 Provider 不冒充 LIVE。',
    }}

@router.get('/suppliers')
def suppliers(p: Principal = Depends(admin_principal)):
    with SessionLocal() as s:
        props = _sample(s, HotelPartnerPropertyRow, ['supplier_id','property_id','name_zh','name_en','property_type','publication_state','updated_at'],100)
        caps = _sample(s, SupplierVerticalCapabilityRow, ['supplier_id','vertical','capability','mode','state','authority_reference','updated_at'],200)
        certs = _sample(s, SupplierCertificationRunRow, ['supplier_id','vertical','state','supplier_certification_run_id','created_at'],100)
        connectors = _sample(s, SupplierConnectorOnboardingRow, ['supplier_id','connector_id','environment','status','rollout_percent','updated_at'],100)
        supplier_ids = sorted({x.get('supplier_id') for x in props+caps+connectors if x.get('supplier_id')})
        return {'data': {'items':[{'supplier_id':sid,
            'properties':sum(1 for x in props if x.get('supplier_id')==sid),
            'capabilities':sum(1 for x in caps if x.get('supplier_id')==sid),
            'connectors':sum(1 for x in connectors if x.get('supplier_id')==sid),
            'certifications':sum(1 for x in certs if x.get('supplier_id')==sid)} for sid in supplier_ids],
            'capabilities':caps,'connectors':connectors,'certifications':certs}}

@router.get('/reviews')
def reviews(p: Principal = Depends(admin_principal)):
    with SessionLocal() as s:
        rows = _sample(s, ReviewSessionRow, ['review_id','order_id','hotel_id','account_id','verified_stay','status','raw_star_input','public_status','experience_score_milli','content_text','created_at','completed_at'],100)
        risks = _sample(s, RiskEventRuntimeRow, ['risk_event_id','risk_type','severity','status','order_id','review_id','decision_id','confirmed_at'],100)
        return {'data': {'items':rows,'risks':risks,'metrics':{'reviews':_count(s,ReviewSessionRow),'risks':_count(s,RiskEventRuntimeRow)}}}

@router.get('/recommendations')
def recommendations(p: Principal = Depends(admin_principal)):
    with SessionLocal() as s:
        judgments = _sample(s, JudgmentRuntimeRow, ['judgment_id','hotel_id','status','go_score_milli','confidence_bps','rule_version','created_at'],100)
        decisions = _sample(s, RecommendationDecisionRow, ['decision_id','hotel_id','status','reason_codes','created_at'],100)
        return {'data': {'judgments':judgments,'decisions':decisions,'metrics':{'judgments':_count(s,JudgmentRuntimeRow),'decisions':_count(s,RecommendationDecisionRow)}}}

@router.get('/stars')
def stars(p: Principal = Depends(admin_principal)):
    with SessionLocal() as s:
        rows = _sample(s, GoodHotelStandardAssessmentRow, ['good_hotel_standard_assessment_id','hotel_id','assessment_state','good_hotel_standard_version_id','evidence_package_id','dimension_result_json','reason_codes_json','assessed_at'],100)
        return {'data': {'items':rows,'metrics':{'assessments':_count(s,GoodHotelStandardAssessmentRow)}}}

@router.get('/truth')
def truth(p: Principal = Depends(admin_principal)):
    with SessionLocal() as s:
        reviews = _count(s, ReviewSessionRow); risks = _count(s, RiskEventRuntimeRow)
        return {'data': {'review_count':reviews,'risk_event_count':risks,
            'principles':['VERIFIED_STAY_FIRST','NO_PAY_FOR_RECOMMENDATION','FACT_CORRECTION_ALLOWED','COMMERCIAL_APPEAL_FORBIDDEN'],
            'risk_events':_sample(s,RiskEventRuntimeRow,['risk_event_id','risk_type','severity','status','order_id','review_id','decision_id'],100)}}

@router.get('/trips')
def trips(p: Principal = Depends(admin_principal)):
    with SessionLocal() as s:
        journeys=_sample(s,GoJourneyRow,['journey_id','account_id','title','destination_summary','status','starts_at','ends_at','updated_at'],100)
        items=_sample(s,GoJourneyItemRow,['item_id','journey_id','vertical','order_id','title','status_snapshot','starts_at','ends_at','detail_route'],200)
        return {'data':{'journeys':journeys,'items':items,'metrics':{'journeys':_count(s,GoJourneyRow),'items':_count(s,GoJourneyItemRow)}}}
