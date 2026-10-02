from pydantic import BaseModel, ConfigDict, Field, field_validator


class RefundConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quote_hash: str = Field(strict=True, pattern=r'^[0-9a-f]{64}$')
    confirmed: bool = Field(strict=True)

    @field_validator('confirmed')
    @classmethod
    def explicit_acceptance(cls, value):
        if value is not True:
            raise ValueError('EXPLICIT_REFUND_CONFIRMATION_REQUIRED')
        return value


def revalidate_completed_receipt(read_order, verify_receipt, cached, vertical):
    """A generic HTTP replay cache cannot certify current financial truth."""
    from fastapi import HTTPException
    try:
        order = read_order()
        if order.get('vertical') != vertical:
            return cached  # Other verticals retain their existing replay contract.
        if order.get('status') != 'REFUNDED':
            raise ValueError('REFUND_COMPLETION_EVIDENCE_INVALID')
        verified = verify_receipt()
        if verified != cached:
            raise ValueError('REFUND_COMPLETION_EVIDENCE_INVALID')
        return verified
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
