import re, os, json, collections, sys

# Path to the AUDITED source tree (PR376 head). Not a fixed machine path.
#   git fetch origin pull/376/head:refs/remotes/origin/pr376
#   git worktree add --detach /tmp/pr376 refs/remotes/origin/pr376
#   python inv_api2.py /tmp/pr376/application/src/go_hotel      # or: GO_AUDIT_SRC=...
ROOT = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GO_AUDIT_SRC"))
if not ROOT:
    raise SystemExit("usage: inv_api2.py <path>/application/src/go_hotel   (or set GO_AUDIT_SRC)")


def balanced(t, i):
    j, d = i, 0
    while j < len(t):
        if t[j] == "(":
            d += 1
        elif t[j] == ")":
            d -= 1
            if d == 0:
                return t[i + 1:j]
        j += 1
    return t[i:]

def deps(t):
    out, i = [], 0
    while True:
        i = t.find("Depends(", i)
        if i < 0:
            break
        inner = balanced(t, i + len("Depends")).strip()
        m = re.match(r"require_permission\(\s*['\"]([^'\"]+)['\"]", inner)
        out.append("perm:" + m.group(1) if m else inner)
        i += len("Depends") + 1
    return out

routes = []
files_seen = 0
for dp, _, fs in os.walk(os.path.join(ROOT, "api", "routes")):
    for f in sorted(fs):
        if not f.endswith(".py"):
            continue
        files_seen += 1
        p = os.path.join(dp, f)
        src = open(p, encoding="utf-8").read()
        routers = {}
        for m in re.finditer(r"^(\w+)\s*=\s*APIRouter\s*\(", src, re.M):
            body = balanced(src, m.end() - 1)
            pm = re.search(r"prefix\s*=\s*['\"]([^'\"]*)['\"]", body)
            routers[m.group(1)] = {"prefix": pm.group(1) if pm else "", "deps": deps(body)}
        for m in re.finditer(r"@(\w+)\.(get|post|put|patch|delete)\s*\(", src):
            var, method = m.group(1), m.group(2).upper()
            if var not in routers:
                continue
            inner = balanced(src, m.end() - 1)
            pm = re.match(r"\s*['\"]([^'\"]+)['\"]", inner)
            if not pm:
                continue
            after = src[m.end() + len(inner): m.end() + len(inner) + 1200]
            di = after.find("def ")
            sig = after[di:di + 900] if di >= 0 else after
            alld = sorted(set(routers[var]["deps"] + deps(inner) + deps(sig)))
            routes.append({"method": method, "path": routers[var]["prefix"] + pm.group(1),
                           "deps": alld, "file": os.path.relpath(p, ROOT)})

json.dump(routes, open("api_routes.json", "w"), indent=0)
print("FILES", files_seen, "ROUTES", len(routes))
n = [r for r in routes if not r["deps"]]
print("NO-AUTH ROUTES:", len(n))
c = collections.Counter(r["file"].split(os.sep)[-1] for r in n)
print("\nBY FILE:")
for k, v in c.most_common(30):
    print(f"  {v:3d}  {k}")
print("\n=== INTERNAL no-auth ===")
for r in n:
    if r["path"].startswith("/internal"):
        print(f"  {r['method']:6s} {r['path']}")
