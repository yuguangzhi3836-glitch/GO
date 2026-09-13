from fastapi import APIRouter
from go_hotel.services.p0_design_code_freeze import static_review, PROVIDER_BLUEPRINT, CANCEL_REFUND_TRANSITIONS

router=APIRouter(prefix='/internal/v1/p0/design-code-freeze',tags=['P0 Design Code Freeze'])

@router.get('/status')
def status():
    return static_review()

@router.get('/providers')
def providers():
    return PROVIDER_BLUEPRINT

@router.get('/cancel-refund-state-machine')
def cancel_refund_state_machine():
    return {
        state:[{"target":r.target,"actors":r.actors,"required_evidence":r.required_evidence,"refund_dispositions":r.refund_dispositions} for r in rules]
        for state,rules in CANCEL_REFUND_TRANSITIONS.items()
    }
