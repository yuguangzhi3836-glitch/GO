import json, os, re, sys

# Path to the AUDITED source tree (PR376 head). Not a fixed machine path.
GO_SRC = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GO_AUDIT_SRC"))
if not GO_SRC:
    raise SystemExit("usage: classify.py <path>/application/src/go_hotel   (or set GO_AUDIT_SRC)")
WT = GO_SRC

RS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'api_routes.json')))

n = [r for r in RS if not r['deps']]
out = []
for r in sorted(n, key=lambda x: x['path']):
    rel = r['file'].replace(os.sep, '/')
    f = os.path.join(WT, rel)
    src = open(f, encoding='utf-8').read() if os.path.exists(f) else ''
    tail = r['path'].rstrip('/').split('/')[-1] or ''
    pos = 0
    if tail:
        m = re.search(r"@\w+\.\w+\s*\(\s*['\"]\.?/?" + re.escape(tail) + r"['\"]", src)
        if m:
            pos = m.end()
    di = src.find('def ', pos)
    sig = src[di:di + 300].split('\n')[0] if di >= 0 else ''
    out.append({"method": r['method'], "path": r['path'], "file": rel, "sig": sig})

json.dump(out, open('unauth_raw.json', 'w'), indent=1, ensure_ascii=False)
for o in out:
    print(o['method'] + "\t" + o['path'] + "\t" + o['file'].split('/')[-1])
