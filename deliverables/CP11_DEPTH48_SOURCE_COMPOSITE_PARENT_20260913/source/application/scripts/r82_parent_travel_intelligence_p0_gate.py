from __future__ import annotations
import ast, json, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
errors=[]
required=[
 "src/go_hotel/travel_intelligence/contracts.py","src/go_hotel/travel_intelligence/cost_governor.py","src/go_hotel/travel_intelligence/service.py","src/go_hotel/api/routes/travel_intelligence.py","alembic/versions/0112_travel_intelligence_p0.py",
 "specs/travel_intelligence/event_schema.v1.json","specs/travel_intelligence/event_type_registry.v1.json","specs/travel_intelligence/ai_decision_integrity.v1.json","specs/model_gateway/cost_governor_policy.v1.json"]
for rel in required:
 p=ROOT/rel
 if not p.exists():errors.append("MISSING:"+rel)
for rel in ["src/go_hotel/travel_intelligence/contracts.py","src/go_hotel/travel_intelligence/cost_governor.py","src/go_hotel/travel_intelligence/service.py","src/go_hotel/api/routes/travel_intelligence.py","alembic/versions/0112_travel_intelligence_p0.py"]:
 try: ast.parse((ROOT/rel).read_text(),filename=rel)
 except Exception as e:errors.append(f"SYNTAX:{rel}:{e}")
for rel in ["specs/travel_intelligence/event_schema.v1.json","specs/travel_intelligence/event_type_registry.v1.json","specs/travel_intelligence/ai_decision_integrity.v1.json","specs/model_gateway/cost_governor_policy.v1.json"]:
 try: json.loads((ROOT/rel).read_text())
 except Exception as e:errors.append(f"JSON:{rel}:{e}")
service=(ROOT/'src/go_hotel/travel_intelligence/service.py').read_text()
for token in ['TRANSACTION_TRUTH_DOMAINS','projection_only','MODEL_GATEWAY_EXTERNAL_EGRESS_DENIED','decision_hash','idempotency_key']:
 if token not in service and token not in (ROOT/'src/go_hotel/travel_intelligence/cost_governor.py').read_text():errors.append('CONTROL_MISSING:'+token)
main=(ROOT/'src/go_hotel/main.py').read_text()
if 'travel_intelligence_router' not in main:errors.append('ROUTER_NOT_REGISTERED')
if errors:
 print('R8.2_PARENT_TRAVEL_INTELLIGENCE_P0_GATE: BLOCK'); [print(x) for x in errors]; sys.exit(1)
print('R8.2_PARENT_TRAVEL_INTELLIGENCE_P0_GATE: PASS')
