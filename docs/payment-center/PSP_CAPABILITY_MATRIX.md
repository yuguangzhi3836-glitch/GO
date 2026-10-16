# D05 — PSP Capability Matrix (First-Pass Documentation Verification)

Status: DOCUMENTED_CAPABILITY_ONLY
Evidence baseline date: 2026-09-13
Scope: WeChat Pay / Alipay / international-card acquiring for HOTEL P0
Sandbox execution status: NOT_RUN
Live money: LOCKED

## 1. Evidence rule

This file records only documented provider capability and current GO repository readiness.

It does **not** prove:

- GO merchant eligibility;
- hotel sub-merchant approval;
- actual contracted product rights;
- Sandbox edge-case behavior;
- real money behavior;
- production callback/network behavior.

Those remain NOT_VERIFIED until provider account/Sandbox evidence exists.

## 2. WeChat Pay — documented facts

### Candidate merchant shape

WeChat Pay partner-mode Native documentation supports a service-provider merchant plus `sub_mchid` / sub-merchant identifier.

Official partner guidance states that `sub_mchid` is the receiving sub-merchant and successful-order funds enter that sub-merchant's basic account.

This is directionally compatible with the approved GO business rule that the hotel, not GO, is the room-charge collection主体.

It is **not** proof that GO or any hotel is currently approved for this mode.

### Native transaction creation

Native order API creates a WeChat payment order and returns `code_url`; the merchant frontend renders it as a QR code.

### Expiry semantics

Official Native documentation distinguishes at least two clocks:

- `time_expire`: merchant-defined payment end time. It can be configured within provider limits; official docs state it cannot be earlier than one minute after order creation and cannot exceed seven days.
- `code_url`: QR URL is documented as valid for two hours; after that the same order parameters may need to be used to obtain a new code URL.

The docs explicitly state that payment end time is not the same as order close time. Merchants should call the close-order API when appropriate after payment expiry.

Therefore GO must not equate QR lifetime, payment eligibility lifetime, internal checkout-page lifetime and inventory-reservation lifetime.

### Close / query / callback

Official docs provide:

- close-order API for unpaid orders;
- query by merchant order number / WeChat transaction ID;
- asynchronous payment-success callback to the merchant `notify_url`.

A callback cannot be the only recovery mechanism because query capability exists and network/callback delivery can fail.

### Refund

Official refund APIs support full or partial refund. Provider documentation warns that an accepted refund request is not itself final refund success; result notification/query is authoritative for the final outcome.

Stable merchant refund identity must be preserved for retry to avoid duplicate refunds.

### HOTEL P0 open questions

- Which WeChat product/mode will GO actually contract: service-provider partner mode, direct merchant, APP/JSAPI/Native/H5 combination?
- Can each hotel be onboarded as the required sub-merchant under GO's legal/commercial setup?
- Does the selected product offer any real authorization/hold model suitable for the approved "hotel cannot freely use room-charge funds before release" goal, or will P0 need delayed settlement / another supported mechanism?
- How do close/query/callback race under Sandbox in the exact P0 mode?

WECHAT_SANDBOX_STATUS=NOT_VERIFIED

## 3. Alipay — documented facts

### Merchant/service-provider shape

Alipay Open Platform documents service-provider onboarding, merchant signing/authorization, and payment products such as in-person payment, WAP and APP payment.

Official service-provider guidance says merchants provide/verify their own entity and bank settlement-account information and authorize the service provider application before the service provider can initiate payment transactions on the merchant's behalf.

This is directionally compatible with hotel-as-merchant, but actual GO/hotel eligibility is not proven.

### Sandbox

Alipay Open Platform documents a Sandbox environment and demonstrates `alipay.trade.precreate` using Sandbox app ID, gateway, keys and Alipay public key.

### QR / transaction timing

Alipay's documented precreate flow returns a QR code and supports a transaction timeout field such as `timeout_express`; official/official-platform material documents the QR code as time-limited and the transaction as having a merchant-defined timeout.

Exact limits and behavior must be revalidated against the current product contract/Sandbox rather than copied from historical examples.

### Query / close / cancel / refund

Alipay payment API documentation exposes:

- `alipay.trade.query`;
- `alipay.trade.close`;
- `alipay.trade.cancel`;
- `alipay.trade.refund`;
- refund query APIs.

Official API guidance specifically identifies query as necessary when the merchant/network/server did not receive a payment notification or the payment result is unknown.

The cancel API is documented for timeout/unknown payment results: query first, then cancel when there is no definite result. If the customer actually paid, the cancel flow may return funds; normal successful transactions should use refund instead.

### Authorization/freeze capability

The Alipay payment API catalog includes funds-authorization/freeze APIs such as `alipay.fund.auth.order.freeze`.

This only proves that an authorization/freeze product exists in the platform catalog. It does **not** prove that:

- the hotel-booking P0 merchant category is eligible;
- the duration fits a hotel stay;
- all intended funding sources support it;
- GO's service-provider/sub-merchant arrangement may use it;
- release/capture semantics meet management's approved business objective.

Those require product-contract and Sandbox evidence.

ALIPAY_SANDBOX_STATUS=AVAILABLE_IN_PLATFORM_BUT_GO_NOT_TESTED

## 4. International cards — current blocker

Current GO repository enumerates generic channel labels including VISA, MASTERCARD, AMEX, JCB and UNIONPAY_CARD.

No concrete international-card acquirer / PSP / hosted-checkout product was found in the inspected repository baseline.

Without a selected provider and product, it is not technically meaningful to claim exact behavior for:

- authorize/capture duration;
- incremental or delayed capture;
- void/reversal;
- 3-D Secure;
- card tokenization;
- hosted checkout return/callback semantics;
- refund idempotency;
- chargeback/dispute webhooks;
- settlement timing;
- hotel sub-merchant / descriptor behavior.

The project must first select one or more candidate acquirers/products through management/commercial/security review. D05 must then be repeated against those exact official APIs and Sandbox environments.

CARD_ACQUIRER_STATUS=PROVIDER_NOT_SELECTED
CARD_SANDBOX_STATUS=NOT_AVAILABLE_TO_TEST

## 5. Current GO integration readiness

Repository evidence currently shows:

- native HOTEL uses `MockPaymentProvider`;
- omnichannel payment has channel labels and merchant-binding concepts;
- omnichannel `execute()` only allows `CONTRACT_SIMULATOR` and rejects real external execution;
- checkout readiness reports external executor not configured unless certified merchant binding exists, and still reports `external_live=False` in inspected code.

Therefore no provider above can currently be described as integrated into GO HOTEL P0 from repository evidence.

## 6. Required Sandbox evidence plan

For each actually selected provider/product, create an evidence pack covering at minimum:

1. create payment / authorize with a stable merchant order ID;
2. exact merchant/sub-merchant identity observed;
3. configured expiry and actual expiry behavior;
4. close/void before payment;
5. query after client/network timeout;
6. callback signature verification and duplicate callback replay;
7. callback loss followed by query recovery;
8. payment at/near expiry boundary;
9. close racing late payment;
10. full refund;
11. partial refund;
12. duplicate refund retry with same idempotency identity;
13. refund timeout and query recovery;
14. merchant account/settlement identity evidence;
15. authorization/hold/capture/release tests where the contracted product supports them.

No inventory behavior should be inferred from PSP behavior. Inventory reserve tests belong to D02 and the later integrated transaction review.

## 7. Documentation sources reviewed

### WeChat Pay official

- Native order, merchant documentation: https://pay.wechatpay.cn/doc/v3/merchant/4012791877
- Native development guide: https://pay.wechatpay.cn/doc/v3/merchant/4012791891
- Partner-mode Native order / sub-merchant: https://pay.wechatpay.cn/doc/v3/partner/4012523551
- Partner-mode Native guide: https://pay.wechatpay.cn/doc/v3/partner/4012076269
- Close order: https://pay.wechatpay.cn/doc/v3/merchant/4012526915
- Payment-success callback: https://pay.wechatpay.cn/doc/v3/merchant/4012791861
- Query by merchant order number: https://pay.wechatpay.cn/doc/v3/merchant/4013070356

### Alipay official / official platform material

- Service-provider payment integration / Sandbox overview: https://open.alipay.com/paymentServicer/paymentProvider.htm
- Service-provider merchant management: https://open.alipay.com/operatingGuide.htm
- Alipay Open Platform support center: https://open.alipay.com/support/supportCenter.htm
- Payment API catalog / trade query, close, cancel, refund, fund authorization listings: official Alibaba/Alipay developer documentation indexed under `developer.alibaba.com` / Alipay Open Platform.

D05_RESULT=DOCUMENTED_CAPABILITIES_PARTIALLY_ESTABLISHED
D05_BLOCKER_01=GO_WECHAT_PRODUCT_AND_MERCHANT_ELIGIBILITY_NOT_VERIFIED
D05_BLOCKER_02=GO_ALIPAY_PRODUCT_AND_MERCHANT_ELIGIBILITY_NOT_VERIFIED
D05_BLOCKER_03=INTERNATIONAL_CARD_ACQUIRER_NOT_SELECTED
D05_BLOCKER_04=NO_GO_PSP_SANDBOX_EVIDENCE_YET
