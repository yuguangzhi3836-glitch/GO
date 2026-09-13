from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

class Stay(BaseModel):
    check_in: str
    check_out: str

class Destination(BaseModel):
    city_code: str

class Occupancy(BaseModel):
    rooms: int = 1
    adults: int = 2
    children: int = 0

class SearchRequest(BaseModel):
    destination: Destination
    stay: Stay
    occupancy: Occupancy = Occupancy()
    currency: str = "CNY"

class PrebookRequest(BaseModel):
    currency: str = "CNY"

class CreateOrderRequest(BaseModel):
    prebook_id: str
    account_id: str = "acct_demo"
    expected_fare_rule_hash: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    fare_confirmed: bool = Field(default=False, strict=True)

class PaymentRequest(BaseModel):
    payment_method_token: str
    amount_minor: int = Field(gt=0)
    currency: str

class CancellationRequest(BaseModel):
    cancellation_quote_id: str
    reason_code: str = "CHANGE_OF_PLAN"
    quote_hash: str | None = None
    confirmed: bool = Field(default=False, strict=True)

class ChangeQuoteRequest(BaseModel):
    new_check_in: str
    new_check_out: str

class CashFarePaymentRetryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quote_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmed: bool = Field(strict=True)
    payment_method_token: str

class ChangeRequest(BaseModel):
    change_quote_id: str
    payment_method_token: str = "pm_success"
    quote_hash: str | None = None
    confirmed: bool = Field(default=False, strict=True)

class StayCreditRedemptionQuoteRequest(BaseModel):
    check_in: str
    check_out: str

class StayCreditRedeemRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    redemption_quote_id: str
    quote_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmed: Literal[True]
    payment_method_token: str = "pm_success"
    traveler_id: str | None = None
    consent_id: str | None = None

class StayCreditConvertRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quote_id: str
    quote_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmed: Literal[True]

class StayCreditPaymentRetryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quote_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmed: Literal[True]
    payment_method_token: str
