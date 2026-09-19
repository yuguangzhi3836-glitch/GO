"""Independent C13 local reproduction: same signed callback in two sessions."""
import os
import tempfile
from pathlib import Path
import json
import hashlib
import hmac
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

out = Path(__file__).parent
database = Path(tempfile.mkdtemp(prefix="c13_callback_")) / "isolated.sqlite"
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{database}"
os.environ["GO_PAYMENT_WEBHOOK_KEY_ALIPAY"] = "c13-isolated-test-key"

from sqlalchemy import event, select, func
from go_hotel.db.models import Base, OmnichannelWebhookReceiptRow as Receipt
from go_hotel.db.session import engine, SessionLocal
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as svc

Base.metadata.create_all(engine)
intent = svc.create_intent({"business_type": "SUBSCRIPTION_INVOICE", "business_id": "c13-local",
    "payee_id": "GO", "operation": "PAY", "amount_minor": 100, "currency": "CNY",
    "channel_priority": ["ALIPAY"]}, "c13-local-key", "c13-local-payer")
svc.select_channel(intent["payment_intent_id"], "ALIPAY", "c13-local-payer")
attempt = svc.execute(intent["payment_intent_id"])
body = {"external_event_id": "c13-duplicate", "payment_attempt_id": attempt["payment_attempt_id"],
    "external_operation_id": "c13-local-operation", "state": "SUCCEEDED",
    "occurred_at": datetime.now(timezone.utc).isoformat()}
raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
signature = hmac.new(b"c13-isolated-test-key", raw.encode(), hashlib.sha256).hexdigest()
barrier = Barrier(2)

def both_observed_no_receipt(conn, cursor, statement, parameters, context, executemany):
    if statement.startswith("SELECT omnichannel_webhook_receipt.") and "external_event_id =" in statement:
        barrier.wait(timeout=10)

def invoke(_):
    try:
        response = svc.webhook("ALIPAY", body, signature)
        return {"ok": True, "duplicate": response["duplicate"]}
    except Exception as exc:
        return {"ok": False, "exception": type(exc).__name__, "message": str(exc).split("\n")[0]}

event.listen(engine, "after_cursor_execute", both_observed_no_receipt)
try:
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(invoke, range(2)))
finally:
    event.remove(engine, "after_cursor_execute", both_observed_no_receipt)
with SessionLocal() as session:
    receipts = session.scalar(select(func.count()).select_from(Receipt))
result = {"scope": "Local isolated SQLite; no real provider calls", "outcomes": outcomes,
    "receipt_count": receipts, "expected": "Both calls succeed; exactly one duplicate and one receipt",
    "reproduced": not all(value["ok"] for value in outcomes)}
(out / "callback-race-reproduction.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
engine.dispose()
