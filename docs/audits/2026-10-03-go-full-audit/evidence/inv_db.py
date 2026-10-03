import re, os, json, collections

WT = "D:/Code/Workbuddy/GO-SUPAUDIT376/wt/application"
SRC = os.path.join(WT, "src", "go_hotel")
MODELS = os.path.join(SRC, "db", "models.py")

src = open(MODELS, encoding="utf-8").read()
classes = []
for m in re.finditer(r"^class\s+(\w+)\s*\(Base\)\s*:(.*?)(?=^class\s|\Z)", src, re.M | re.S):
    cls, body = m.group(1), m.group(2)
    tn = re.search(r"__tablename__\s*=\s*['\"]([^'\"]+)['\"]", body)
    classes.append({"cls": cls, "table": tn.group(1) if tn else "(none)"})
print("MODEL CLASSES:", len(classes))

# build corpus of all application source (excluding models.py itself and tests)
corpus = {}
for dp, _, fs in os.walk(SRC):
    for f in fs:
        if not f.endswith(".py"):
            continue
        p = os.path.join(dp, f)
        if os.path.normcase(p) == os.path.normcase(MODELS):
            continue
        corpus[os.path.relpath(p, SRC)] = open(p, encoding="utf-8").read()

testcorpus = {}
for dp, _, fs in os.walk(os.path.join(WT, "tests")):
    for f in fs:
        p = os.path.join(dp, f)
        testcorpus[os.path.relpath(p, WT)] = open(p, encoding="utf-8", errors="ignore").read()

rows = []
for c in classes:
    cls, table = c["cls"], c["table"]
    app_files, test_files = [], []
    for rel, txt in corpus.items():
        if re.search(r"\b" + re.escape(cls) + r"\b", txt):
            app_files.append(rel)
        elif re.search(r"['\"]" + re.escape(table) + r"['\"]", txt):
            app_files.append(rel + "(by-table)")
    for rel, txt in testcorpus.items():
        if re.search(r"\b" + re.escape(cls) + r"\b", txt):
            test_files.append(rel)
    svc = [f for f in app_files if f.startswith("services" + os.sep) or f.startswith("services/")]
    rt = [f for f in app_files if f.startswith("api" + os.sep) or f.startswith("api/")]
    wk = [f for f in app_files if f.startswith("workers" + os.sep) or f.startswith("workers/")]
    rows.append({"cls": cls, "table": table, "app_refs": len(app_files),
                 "svc": len(svc), "route": len(rt), "worker": len(wk),
                 "test_refs": len(test_files),
                 "only_tests": len(app_files) == 0 and len(test_files) > 0,
                 "orphan": len(app_files) == 0 and len(test_files) == 0})

json.dump(rows, open("db_tables.json", "w"), indent=0)
print("\nCLASSIFICATION:")
print(f"  referenced in app source : {sum(1 for r in rows if r['app_refs']>0)}")
print(f"  TEST-ONLY (no app ref)   : {sum(1 for r in rows if r['only_tests'])}")
print(f"  ORPHAN (no ref at all)   : {sum(1 for r in rows if r['orphan'])}")
print(f"  service-referenced       : {sum(1 for r in rows if r['svc']>0)}")
print(f"  route-referenced         : {sum(1 for r in rows if r['route']>0)}")
print(f"  worker-referenced        : {sum(1 for r in rows if r['worker']>0)}")
print("\nTOP 15 most-referenced tables:")
for r in sorted(rows, key=lambda x: -x["app_refs"])[:15]:
    print(f"  {r['app_refs']:4d}  {r['table']}")
print("\nORPHAN / TEST-ONLY tables (first 40):")
for r in rows:
    if r["only_tests"] or r["orphan"]:
        tag = "TEST_ONLY" if r["only_tests"] else "ORPHAN"
        print(f"  {tag:9s} {r['table']}  ({r['cls']})")
