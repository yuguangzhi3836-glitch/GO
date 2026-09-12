# Offline / Network Recovery Contract

1. GET/read operations fail fast with `NETWORK_OFFLINE` and can be retried after connectivity returns.
2. Booking, payment, change, cancel, refund and Stay Credit financial mutations are **not** blindly queued offline.
3. Every online mobile mutation carries an `Idempotency-Key`.
4. If the network is lost after an external side effect may have occurred, the backend Saga/Reconciliation path is authoritative; the client reloads Trips/order state rather than resubmitting.
5. Quick Review may be retried by the user after reconnecting; backend single-review/idempotency rules prevent duplicate completion.
6. Push/inbox is advisory. ConsumerNotification remains available even if OS push permission is denied.
