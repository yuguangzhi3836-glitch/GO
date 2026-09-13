from fastapi import APIRouter, Depends
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderRow, ReviewSessionRow, RiskEventRuntimeRow, JudgmentRuntimeRow, RecommendationDecisionRow, GoodHotelStandardAssessmentRow, HotelPartnerPropertyRow
from go_hotel.security.deps import supplier_principal
from go_hotel.security.service import Principal

router=APIRouter(prefix='/v1/supplier/operations',tags=['supplier-operations-console'])

def d(row,fields): return {f:getattr(row,f,None) for f in fields}

@router.get('/reviews')
def reviews(p:Principal=Depends(supplier_principal)):
    with SessionLocal() as s:
        order_ids=set(s.scalars(select(OrderRow.order_id).where(OrderRow.supplier_id==p.supplier_id)).all())
        rs=s.scalars(select(ReviewSessionRow).where(ReviewSessionRow.order_id.in_(order_ids)).limit(200)).all() if order_ids else []
        risk=s.scalars(select(RiskEventRuntimeRow).where(RiskEventRuntimeRow.order_id.in_(order_ids)).limit(200)).all() if order_ids else []
        return {'data':{'items':[d(x,['review_id','order_id','hotel_id','verified_stay','status','raw_star_input','public_status','experience_score_milli','content_text','completed_at']) for x in rs],
                        'risks':[d(x,['risk_event_id','order_id','review_id','risk_type','severity','status','decision_id']) for x in risk]}}

@router.get('/judgment')
def judgment(p:Principal=Depends(supplier_principal)):
    with SessionLocal() as s:
        hotel_ids=set(s.scalars(select(HotelPartnerPropertyRow.property_id).where(HotelPartnerPropertyRow.supplier_id==p.supplier_id)).all())
        js=s.scalars(select(JudgmentRuntimeRow).where(JudgmentRuntimeRow.hotel_id.in_(hotel_ids)).limit(200)).all() if hotel_ids else []
        rec=s.scalars(select(RecommendationDecisionRow).where(RecommendationDecisionRow.hotel_id.in_(hotel_ids)).limit(200)).all() if hotel_ids else []
        stars=s.scalars(select(GoodHotelStandardAssessmentRow).where(GoodHotelStandardAssessmentRow.hotel_id.in_(hotel_ids)).limit(200)).all() if hotel_ids else []
        return {'data':{'judgments':[d(x,['judgment_id','hotel_id','status','go_score_milli','confidence_bps','rule_version','created_at']) for x in js],
                        'recommendations':[d(x,['decision_id','hotel_id','status','reason_codes','public_go_score_milli','created_at']) for x in rec],
                        'star_assessments':[d(x,['good_hotel_standard_assessment_id','hotel_id','assessment_state','good_hotel_standard_version_id','reason_codes_json','assessed_at']) for x in stars],
                        'commercial_appeal_allowed':False,'fact_correction_allowed':True}}
