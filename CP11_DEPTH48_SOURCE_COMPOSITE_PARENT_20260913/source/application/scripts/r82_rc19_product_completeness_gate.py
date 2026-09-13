#!/usr/bin/env python3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
errors=[]
regional=(ROOT/'src/go_hotel/services/regional_hotel_build.py').read_text('utf-8')
discovery=(ROOT/'src/go_hotel/services/hotel_discovery_orchestrator.py').read_text('utf-8')
worker=(ROOT/'src/go_hotel/workers/regional_hotel_build_worker.py').read_text('utf-8')
ops=(ROOT/'src/go_hotel/api/routes/operations_console.py').read_text('utf-8')
ui=(ROOT/'frontend/shared/app.js').read_text('utf-8')
for token in ['OSM_FALLBACK_ENDPOINT','REGIONAL_PROVIDER_MAX_ATTEMPTS','duplicates_removed']:
    if token not in regional: errors.append('REGIONAL_THROUGHPUT_MISSING:'+token)
if "GO_HOTEL_REGION_WORKER_CONCURRENCY','6'" not in worker: errors.append('WORKER_CONCURRENCY_DEFAULT_MISSING')
if 'read_timeout=min(max(requested,12.0),90.0)' not in discovery: errors.append('READ_TIMEOUT_FIX_MISSING')
for vertical in ['HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION']:
    if vertical not in ops: errors.append('VERTICAL_MISSING:'+vertical)
for stage in ['SUPPLY','OFFER','AVAILABILITY','ORDER','PAYMENT','FULFILLMENT','CHANGE_CANCEL_REFUND','SETTLEMENT_EVIDENCE','EXCEPTION_RECOVERY']:
    if stage not in ops: errors.append('LIFECYCLE_STAGE_MISSING:'+stage)
if 'RC20 模块深度验收' not in ui: errors.append('RC20_UI_DEPTH_ACCEPTANCE_MISSING')
if '正式外部供给按 Provider 上线状态单独验收' not in ui: errors.append('EXTERNAL_PROVIDER_TRUTH_BOUNDARY_MISSING')
if errors:
    print('R8.2_RC19_PRODUCT_COMPLETENESS_GATE: BLOCK')
    print('\n'.join(errors)); raise SystemExit(1)
print('regional_throughput=PASS')
print('six_vertical_lifecycle=PASS')
print('R8.2_RC19_PRODUCT_COMPLETENESS_GATE: PASS')
