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
