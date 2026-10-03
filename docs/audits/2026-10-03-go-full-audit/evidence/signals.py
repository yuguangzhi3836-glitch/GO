import json, os, re

WT = "D:/Code/Workbuddy/GO-SUPAUDIT376/wt/application/src/go_hotel"
raw = json.load(open('unauth_raw.json'))

SIGNALS = [
    ('_consumer_account', 'consumer session helper (raises 401)'),
    ('current_principal', 'calls principal resolver in body'),
    ('_require_consumer', 'consumer guard'),
    ('_admin(', 'admin guard'),
    ('require_permission', 'permission helper'),
    ('principal(', 'principal call'),
    ('_principal', 'principal helper'),
    ('X-Approval-ID', 'approval header'),
    ('X-Internal', 'internal shared secret header'),
    ('secret', 'literal secret check'),
    ('hmac', 'signature verification'),
    ('verify_signature', 'signature verification'),
    ('HTTPException(status_code=401', 'explicit 401'),
]

rows = []
for r in raw:
    f = os.path.join(WT, r['file'])
    src = open(f, encoding='utf-8').read()
    tail = r['path'].rstrip('/').split('/')[-1] or ''
    pos = 0
    if tail:
        m = re.search(r"@\w+\.\w+\s*\(\s*['\"]\.?/?" + re.escape(tail) + r"['\"]", src)
        if m:
            pos = m.end()
    di = src.find('def ', pos)
    body = src[di:di + 1400] if di >= 0 else ''
    hits = [label for pat, label in SIGNALS if pat in body]
    rows.append({"method": r['method'], "path": r['path'], "file": r['file'],
                 "sig": r['sig'], "body_signals": hits})

json.dump(rows, open('unauth_signals.json', 'w'), indent=1, ensure_ascii=False)
print("ROUTES WITH BODY-LEVEL AUTH SIGNAL:")
for r in rows:
    if r['body_signals']:
        print("  " + r['method'] + " " + r['path'] + "  <= " + "; ".join(r['body_signals']))
print()
print("ROUTES WITH NO AUTH SIGNAL AT ALL:", sum(1 for r in rows if not r['body_signals']))
