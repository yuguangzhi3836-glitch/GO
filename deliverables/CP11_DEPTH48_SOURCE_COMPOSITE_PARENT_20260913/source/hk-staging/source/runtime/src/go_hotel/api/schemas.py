from pydantic import BaseModel, Field

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
    guests: list[dict] = Field(default_factory=list)
    traveler_ids: list[str] = Field(default_factory=list)
    vault_release_ids: list[str] = Field(default_factory=list)

class PaymentRequest(BaseModel):
    payment_method_token: str
    amount_minor: int = Field(gt=0)
    currency: str

class CancellationRequest(BaseModel):
    cancellation_quote_id: str
    reason_code: str = "CHANGE_OF_PLAN"

class ChangeQuoteRequest(BaseModel):
    new_check_in: str
    new_check_out: str

class ChangeRequest(BaseModel):
    change_quote_id: str
    payment_method_token: str = "pm_success"

class StayCreditRedemptionQuoteRequest(BaseModel):
    check_in: str
    check_out: str

class StayCreditRedeemRequest(BaseModel):
    redemption_quote_id: str
    payment_method_token: str = "pm_success"
