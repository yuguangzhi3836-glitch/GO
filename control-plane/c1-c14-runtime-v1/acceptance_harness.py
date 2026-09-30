"""Machine-readable isolated PostgreSQL acceptance harness.

The harness aggregates scenario results produced by isolated workers. It never
creates infrastructure or connects to Production.
"""
from __future__ import annotations
import argparse,hashlib,json
from dataclasses import dataclass,asdict
from pathlib import Path
from xml.etree.ElementTree import Element,SubElement,ElementTree

REQUIRED=(
 "claim_contention","duplicate_dispatch","effect_idempotency","worker_death",
 "database_restart","old_worker_fencing","retry_exhaustion","evidence_projection"
)

@dataclass(frozen=True)
class Scenario:
 name:str
 passed:bool
 details:dict

def load_results(path:Path)->list[Scenario]:
 data=json.loads(path.read_text())
 return [Scenario(str(x["name"]),x["passed"],dict(x.get("details",{}))) for x in data["scenarios"]]

def evaluate(items:list[Scenario])->dict:
 by={x.name:x for x in items}
 missing=[x for x in REQUIRED if x not in by]
 failed=[x for x in REQUIRED if x in by and by[x].passed is not True]
 duplicates=sorted({x.name for x in items if sum(y.name == x.name for y in items)>1})
 invalid=sorted({x.name for x in items if type(x.passed) is not bool})
 return {"verdict":"PASS" if not missing and not failed and not duplicates and not invalid else "FAIL","missing":missing,"failed":failed,
         "required":list(REQUIRED),"observed":sorted(by),"duplicates":duplicates,"invalid":invalid}

def write_junit(items:list[Scenario],out:Path)->None:
 suite=Element("testsuite",name="c1-c14-postgres-acceptance",tests=str(len(items)),
               failures=str(sum(x.passed is not True for x in items)))
 for x in items:
  case=SubElement(suite,"testcase",name=x.name)
  if x.passed is not True:
   f=SubElement(case,"failure",message="scenario failed"); f.text=json.dumps(x.details,sort_keys=True)
 ElementTree(suite).write(out,encoding="utf-8",xml_declaration=True)

def sha256(path:Path)->str:
 h=hashlib.sha256()
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
 return h.hexdigest()

def main():
 p=argparse.ArgumentParser(); p.add_argument("results"); p.add_argument("--out",default="acceptance-out")
 a=p.parse_args(); src=Path(a.results); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
 try:
  items=load_results(src); verdict=evaluate(items)
 except (OSError,ValueError,KeyError,TypeError) as exc:
  items=[]; verdict=evaluate(items); verdict["input_error"]=str(exc)
 observed={x.name for x in items}
 junit_items=items+[Scenario(name,False,{"error":"NOT_RUN"}) for name in REQUIRED if name not in observed]
 summary=out/"summary.json"; summary.write_text(json.dumps(verdict,indent=2,sort_keys=True)+"\n")
 junit=out/"junit.xml"; write_junit(junit_items,junit)
 manifest=out/"SHA256SUMS"
 files=[summary,junit]
 if src.exists():
  copied=out/"results.json"
  if src.resolve()!=copied.resolve(): copied.write_bytes(src.read_bytes())
  files.insert(0,copied)
 manifest.write_text("".join(f"{sha256(x)}  {x.name}\n" for x in files))
 print(json.dumps(verdict,sort_keys=True))
 raise SystemExit(0 if verdict["verdict"]=="PASS" else 2)
if __name__=="__main__": main()

