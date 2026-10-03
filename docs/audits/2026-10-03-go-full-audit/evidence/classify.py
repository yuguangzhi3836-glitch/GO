import json, os, re

RS = json.load(open('api_routes.json'))
WT = "D:/Code/Workbuddy/GO-SUPAUDIT376/wt/application/src/go_hotel"

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
