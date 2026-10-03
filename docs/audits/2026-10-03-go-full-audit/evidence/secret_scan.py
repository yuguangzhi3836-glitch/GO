import json, os, re, sys

# Scan ROOT (default: this file's directory) for secret-like patterns.
# Usage: python secret_scan.py [ROOT]
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))

PATTERNS = [
    ("firecrawl_key", r"fc-[0-9a-fA-F]{20,}"),
    ("generic_api_key_assign", r"(?i)(api[_-]?key|apikey|secret|token|password|passwd|pwd)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
    ("bearer", r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
    ("cookie", r"(?i)(set-cookie|cookie)\s*[:=]\s*[^\s\"']{20,}"),
    ("private_key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("aws_ak", r"(?i)AKIA[0-9A-Z]{16}"),
    ("jwt", r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    ("sk_key", r"sk-[A-Za-z0-9]{20,}"),
]

hits = []
scanned = 0
for dp, _, fs in os.walk(ROOT):
    for f in fs:
        p = os.path.join(dp, f)
        if f.endswith(".png"):
            scanned += 1
            continue
        try:
            txt = open(p, encoding="utf-8", errors="ignore").read()
        except Exception as e:
            print("SKIP", p, e)
            continue
        scanned += 1
        for name, pat in PATTERNS:
            for m in re.finditer(pat, txt):
                s = m.group(0)
                # mask the middle of any match before printing
                masked = s[:6] + "***" + s[-3:] if len(s) > 12 else "***"
                hits.append((os.path.relpath(p, ROOT), name, masked))

print("FILES SCANNED:", scanned)
print("SECRET-LIKE HITS:", len(hits))
for p, n, m in hits:
    print("  HIT", p, n, m)
if not hits:
    print("RESULT: CLEAN (no secret-like pattern found in text evidence)")
