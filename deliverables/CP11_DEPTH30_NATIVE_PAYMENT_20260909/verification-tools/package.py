import hashlib,json,shutil,zipfile
from pathlib import Path
from datetime import datetime,timezone

root=Path('/workspace/scratch/f016e17148d8/go-depth30')
parent_package=Path('/workspace/scratch/af00ce8c656d/go-depth29/deliverables/CP11_DEPTH29_TRIP_REENTRY_20260909')
out=root/'deliverables/CP11_DEPTH30_NATIVE_PAYMENT_20260909'
out.mkdir(parents=True,exist_ok=True)
sha=lambda b:hashlib.sha256(b).hexdigest()
tree=lambda fp:sha(''.join(f'{k}\0{v}\n' for k,v in sorted(fp.items())).encode())
write=lambda p,obj:p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
before=json.loads((parent_package/'SOURCE_FINGERPRINT.json').read_text())
assert tree(before)=='ffcea37a3d2ce626026571c1d16eb7be190bd1b048b6b8dfd0d6c8164f2b556c'
new=['AGENTS.md','docs/governance/COMMAND_CENTER_AUTHORITY_20260909.md','docs/governance/DEPTH29_PAYMENT_STATUS_20260909.md',
 'mobile/go-app/src/api/transport.ts','mobile/go-app/src/domain/bookingIntent.ts','mobile/go-app/src/domain/orderActions.ts','mobile/go-app/src/domain/requestFingerprint.ts',
 'mobile/go-app/src/screens/CheckoutScreen.tsx','mobile/go-app/src/screens/RefundScreen.tsx','mobile/go-app/src/components/HotelFareTerms.tsx','mobile/go-app/src/components/OrderActions.tsx',
 'tests_frontend/mobile_transport.test.mjs','tests_frontend/mobile_order_actions.test.mjs','tests_frontend/native_api_bridge.mjs','tests/test_depth30_native_api_contract.py']
final={p:sha((root/p).read_bytes()) for p in sorted(set(before)|set(new))}
changed=[{'path':p,'before_sha256':before.get(p),'sha256':h,'size':(root/p).stat().st_size} for p,h in final.items() if before.get(p)!=h]
manifest={'build':'DEPTH30_NATIVE_PAYMENT','created_at_utc':datetime.now(timezone.utc).isoformat(),'parent_commit':'0451fb095c6fe4a185dcf30931166cebdf27e381',
 'parent_source_tree_sha256':tree(before),'parent_materialized_source_tree_sha256':tree(before),'source_tree_sha256':tree(final),'parent_file_count':len(before),'source_file_count':len(final),'files':changed,
 'additional_input':{'governance_commit':'5d4014253833d4abc8b120dc528fc76d07e5c4c4','paths':new[:3],'authority':'Latest explicit user decision: Command Center owns all development; Hong Kong operations only.'},
 'fingerprint_algorithm':'SHA256 of sorted UTF-8 path + NUL + SHA256 + LF','release_approved':False,'deployed':False}
for name,obj in [('SOURCE_MANIFEST.json',manifest),('SOURCE_FINGERPRINT.json',final),('PARENT_SOURCE_FINGERPRINT.json',before)]:write(out/name,obj)
for row in changed:
    target=out/'source_changes'/row['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((root/row['path']).read_bytes())
with zipfile.ZipFile(out/'GO_CP11_DEPTH30_DELTA_20260909.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for name in ['SOURCE_MANIFEST.json','SOURCE_FINGERPRINT.json','PARENT_SOURCE_FINGERPRINT.json']:z.writestr(name,(out/name).read_bytes())
    for row in changed:z.writestr('source_changes/'+row['path'],(root/row['path']).read_bytes())
gaps=json.loads((parent_package/'KNOWN_GAPS.json').read_text())
gaps['source_tree_sha256']=tree(final)
for g in gaps['gaps']:
    if g['id']=='NATIVE-PENDING-CHECKOUT':
        g.update(state='IMPLEMENTED_SCOPED_VERIFICATION_PENDING',evidence='Six native entry points now share owner-bound checkout/refund, explicit vault references, hotel fare consent, stable request identity, and canonical rereads. Native UI/device and broader aftersales parity remain unverified.')
    if g['id']=='INDEPENDENT-DEPTH29':g.update(id='INDEPENDENT-DEPTH30',state='HOLD',evidence='Await this exact candidate independent CI; previous CI is preserved only as history.')
gaps['gaps'] += [
 {'id':'NATIVE-CHANGE-FLOWS','state':'IMPLEMENTATION_OPEN','source':['mobile/go-app/src/screens/ChangeOrderScreen.tsx','mobile/go-app/src/screens/FlightChangeScreen.tsx','mobile/go-app/src/screens/RailChangeScreen.tsx','mobile/go-app/src/screens/RentalModifyScreen.tsx','mobile/go-app/src/screens/RideModifyScreen.tsx','mobile/go-app/src/screens/AttractionChangeScreen.tsx'],'evidence':'Inspected: hotel change omits confirmed/hash; flight/rail use stale dates and lack error/quote invalidation; attraction hardcodes date/session and immediately executes; rental/ride modify screens do not invoke modification APIs. Not repaired by this payment/refund batch.'},
 {'id':'NONHOTEL-REFUND-CONSENT-BINDING','state':'IMPLEMENTATION_OPEN','evidence':'Client refreshes financial terms immediately before submit. Existing nonhotel refund endpoints do not accept an atomic expected quote/hash confirmation; this client check does not close that server-side race.'},
 {'id':'PAYMENT-PROVIDER-EXECUTOR','state':'IMPLEMENTATION_OPEN','source':'src/go_hotel/connectors/payment_sandbox.py','evidence':'Delegate interface exists; no installed executor implementation was found. Real Alipay sandbox executor gate remains NOT_CONFIGURED. Provider selection and selected official SDK/specification inputs are required to implement/certify it in Command Center. Hong Kong cannot fill this by writing a separate payment system. Live payments are not required for isolated predeployment acceptance.'},
 {'id':'NATIVE-CREATE-UNKNOWN-RECOVERY','state':'LIMITATION','evidence':'An uncertain create stops repeat submission on that mounted screen and routes the user to Trips. No durable cross-device intent journal or explicit intentional duplicate-booking flow is implemented; stable owner/request-body identity prevents automatic duplicate creation for identical retries.'},
]
write(out/'KNOWN_GAPS.json',gaps)
matrix=json.loads((parent_package/'REQUIREMENT_CLOSURE_MATRIX.json').read_text());matrix['source_tree_sha256']=tree(final)
matrix['predeployment_complete']=False;matrix['completion_percentage']=None
matrix['depth30_scope']='Native payment/refund transport and API compatibility only; do not relabel all systems/modules/endpoints as complete.'
write(out/'REQUIREMENT_CLOSURE_MATRIX.json',matrix)
inventory=json.loads((parent_package/'MODULE_SURFACE_INVENTORY.json').read_text());inventory['source_tree_sha256']=tree(final)
inventory['native_screens']=sorted(p for p in final if p.startswith('mobile/go-app/src/screens/') and p.endswith('.tsx'));inventory['native_screen_count']=len(inventory['native_screens'])
write(out/'MODULE_SURFACE_INVENTORY.json',inventory)
write(out/'RELEASE_GATE.json',{'source_tree_sha256':tree(final),'gates':{g:'HOLD' for g in ['THREE_END_REAL_UX_LOGIN','SIX_VERTICAL_REAL_CLOSED_LOOP_E2E','SEALED_NODE_GATE','FINAL_RELEASE']},'predeployment_complete':False,'completion_percentage':None,'deployment_authorized':False,'deployed':False,'hong_kong_running_candidate':'UNKNOWN','scope':'No browser/device/Hong Kong execution; no production transactions. Source/API/unit results cannot close these gates.'})
print(json.dumps({'source_files':len(final),'changed_files':len(changed),'source_tree_sha256':tree(final),'delta_sha256':sha((out/'GO_CP11_DEPTH30_DELTA_20260909.zip').read_bytes())}))
