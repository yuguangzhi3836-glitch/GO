"""Isolated real airport resolver and Pydantic model validation.
Loads only model AST nodes from exact source; no DB/provider/HTTP integration claim.
"""
import ast
import importlib.util
import json
import sys
from pathlib import Path
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
root = Path(__file__).resolve().parents[1]
airport_path = root / "src/go_hotel/flight/airports.py"
spec = importlib.util.spec_from_file_location("release_airports", airport_path)
airports = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = airports
spec.loader.exec_module(airports)
tree = ast.parse((root / "src/go_hotel/flight/journeys.py").read_text())
nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in {"Leg", "JourneySearch"}]
namespace = dict(globals(), resolve_airport=airports.resolve_airport, TripType=Literal["ONE_WAY","ROUND_TRIP","MULTI_CITY"])
exec(compile(ast.Module(body=nodes, type_ignores=[]), "candidate-journey-models", "exec"), namespace)
Search = namespace["JourneySearch"]
day = max(date.today(), date(2026,10,2)).isoformat()
checks = []
for origin, destination in [("福州","哈尔滨"),("福州长乐机场","哈尔滨太平机场"),("foc","hrb"),(" Fuzhou "," Harbin "),("ＦＯＣ","ＨＲＢ")]:
    value = Search(trip_type="ONE_WAY", legs=[dict(origin=origin,destination=destination,departure_date=day)])
    assert (value.legs[0].origin,value.legs[0].destination)==("FOC","HRB")
    checks.append([origin,destination,"FOC","HRB"])
for origin,destination in [("福州","FOC"),("不存在的机场","HRB"),("上海","HRB")]:
    try:
        Search(trip_type="ONE_WAY",legs=[dict(origin=origin,destination=destination,departure_date=day)])
    except ValueError:
        checks.append([origin,destination,"REJECTED"])
    else:
        raise AssertionError((origin,destination))
print(json.dumps({"status":"PASS","model_cases":checks,"scope":"resolver and Pydantic models only; no HTTP/DB/provider"},ensure_ascii=False))
