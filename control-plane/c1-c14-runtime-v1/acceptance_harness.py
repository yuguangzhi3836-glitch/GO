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
 return [Scenario(str(x["name"]),bool(x["passed"]),dict(x.get("details",{}))) for x in data["scenarios"]]

def evaluate(items:list[Scenario])->dict:
 by={x.name:x for x in items}
 missing=[x for x in REQUIRED if x not in by]
 failed=[x for x in REQUIRED if x in by and not by[x].passed]
 return {"verdict":"PASS" if not missing and not failed else "FAIL","missing":missing,"failed":failed,
         "required":list(REQUIRED),"observed":sorted(by)}

def write_junit(items:list[Scenario],out:Path)->None:
 suite=Element("testsuite",name="c1-c14-postgres-acceptance",tests=str(len(items)),
               failures=str(sum(not x.passed for x in items)))
 for x in items:
  case=SubElement(suite,"testcase",name=x.name)
  if not x.passed:
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
 items=load_results(src); verdict=evaluate(items)
 summary=out/"summary.json"; summary.write_text(json.dumps(verdict,indent=2,sort_keys=True)+"\n")
 junit=out/"junit.xml"; write_junit(items,junit)
 manifest=out/"SHA256SUMS"
 files=[src,summary,junit]
 manifest.write_text("".join(f"{sha256(x)}  {x.name}\n" for x in files))
 print(json.dumps(verdict,sort_keys=True))
 raise SystemExit(0 if verdict["verdict"]=="PASS" else 2)
if __name__=="__main__": main()
