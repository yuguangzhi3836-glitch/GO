#!/usr/bin/env python3
from pathlib import Path
import subprocess,sys,json
ROOT=Path(__file__).resolve().parents[1]
errors=[]
ui=(ROOT/'frontend/consumer/app.js').read_text(encoding='utf-8')
for token in ['showHotelSearch()','showFlightSearch()','showRailSearch()','showRideSearch()','showRentalSearch()','showAttractionSearch()']:
    if token not in ui: errors.append('HUMAN_SURFACE_MISSING:'+token)
for token in ['/v1/flights/orders','/v1/rail/orders','/v1/mobility/rides/orders','/v1/mobility/rentals/orders','/v1/attractions/orders','证据链']:
    if token not in ui: errors.append('CONSUMER_LIFECYCLE_MISSING:'+token)
if '该品类正在按真实供给能力逐步开放' in ui: errors.append('GENERIC_CLOSED_VERTICAL_PATH_REMAINS')
if not all(token in ui for token in ['data-home-vertical="MOBILITY"','function showHomeMobilityChooser()','showRentalSearch()','showRideSearch()']):
    errors.append('MOBILITY_HOME_ENTRY_OR_RENTAL_RIDE_REACHABILITY_MISSING')
for rel,tokens in {
    'src/go_hotel/services/rc20_vertical_evidence.py':['previous_hash','entry_hash','list_vertical_evidence'],
    'src/go_hotel/mobility/service.py':['UNKNOWN_EXTERNAL_STATE','RECONCILED_TO_CONFIRMED','FULFILLMENT_'],
    'src/go_hotel/attractions/service.py':['VOUCHER_REDEEMED','SUPPLIER_CLOSED','UNKNOWN_EXTERNAL_STATE'],
    'src/go_hotel/flight/service.py':['RECONCILED_TO_TICKETED','EXTERNAL_STATE_UNKNOWN'],
    'src/go_hotel/rail/service.py':['RECONCILED_TO_TICKETED','EXTERNAL_STATE_UNKNOWN'],
}.items():
    text=(ROOT/rel).read_text(encoding='utf-8')
    for t in tokens:
        if t not in text: errors.append(f'DEPTH_CONTROL_MISSING:{rel}:{t}')
for rel in ['frontend/admin/index.html','frontend/supplier/index.html','frontend/consumer/index.html']:
    if not any(t in (ROOT/rel).read_text(encoding='utf-8') for t in ('20260825-rc20.2','20260825-rc20.3')): errors.append('CACHE_TOKEN_NOT_RC202:'+rel)
if errors:
    print('R8.2_RC20_2_ALL_B_TO_A_GATE: BLOCK')
    for e in errors: print(e)
    sys.exit(1)
proc=subprocess.run([sys.executable,'-m','pytest','-q','tests/test_rc20_2_all_b_to_a.py'],cwd=ROOT)
if proc.returncode:
    print('R8.2_RC20_2_ALL_B_TO_A_GATE: BLOCK')
    print('RC20_2_CLOSURE_TESTS_FAILED')
    sys.exit(proc.returncode)
print('vertical_predeploy_classification=HOTEL:A,FLIGHT:A,RAIL:A,RIDE:A,RENTAL:A,ATTRACTION:A')
print('external_production_live=false')
print('staging_browser_final_evidence=REQUIRED_AFTER_DEPLOYMENT')
print('R8.2_RC20_2_ALL_B_TO_A_GATE: PASS')
