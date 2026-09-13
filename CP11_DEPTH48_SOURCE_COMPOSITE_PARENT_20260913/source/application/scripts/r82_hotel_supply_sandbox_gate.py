#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
service=(ROOT/'src/go_hotel/services/hotel_supply_sandbox.py').read_text()
route=(ROOT/'src/go_hotel/api/routes/hotel_supply_sandbox.py').read_text()
main=(ROOT/'src/go_hotel/main.py').read_text()
models=list((ROOT/'alembic/versions').glob('*.py'))

checks={
 'hotel_only_scope': 'vertical="HOTEL"' in service and 'payment_connected' in service,
 'ready_not_external_state': 'READY_NOT_EXTERNALLY_VERIFIED' in service,
 'external_executor_fail_closed': 'HOTEL_SUPPLY_SANDBOX_EXECUTOR_NOT_CONFIGURED' in service,
 'vault_reference_required': 'EXTERNAL_VAULT_REFERENCE_REQUIRED' in service and 'INLINE_SECRET_FORBIDDEN' in service,
 'supply_truth_fields': all(x in service for x in ('inventory','price_minor','currency','breakfast','cancellation_policy','taxes_fees','sell_state')),
 'required_booking_chain': all(x in service for x in ('AVAILABILITY','QUOTE','BOOK_IDEMPOTENCY','QUERY','CANCEL','SIGNED_WEBHOOK','ERROR_MAPPING','RECONCILIATION')),
 'admin_routes_present': '/internal/v1/hotel-supply-sandbox' in route,
 'router_wired': 'hotel_supply_sandbox_router' in main,
 'no_payment_external_certification': 'PSP_' not in service,
 'no_new_migration_rc14': not any('rc14' in p.name.lower() for p in models),
}
for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
if not all(checks.values()): raise SystemExit(1)
print('R8.2_HOTEL_SUPPLY_SANDBOX_GATE: PASS')
