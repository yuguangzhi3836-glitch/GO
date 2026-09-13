#!/usr/bin/env python3
from pathlib import Path
import hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1]
def block(m): print("R8.2_CONSUMER_VI_REFERENCE10_GATE: BLOCK"); print(m); raise SystemExit(1)
a=json.loads((ROOT/"CONSUMER_VI_REFERENCE_10_0_IMMUTABLE_ALLOWLIST.json").read_text())
for rel,expected in a["files"].items():
 p=ROOT/rel
 if not p.is_file(): block("MISSING:"+rel)
 actual=hashlib.sha256(p.read_bytes()).hexdigest()
 if actual!=expected: block("SHA_MISMATCH:"+rel)
css=(ROOT/"frontend/consumer/vi-reference-10.css").read_text()
app=(ROOT/"frontend/consumer/app.js").read_text()
idx=(ROOT/"frontend/consumer/index.html").read_text()
checks={
 "reference_css_linked":"vi-reference-10.css" in idx,
 "main_lockup_asset":"go-main-lockup.svg" in app,
 "go_ai_asset":"go-ai.svg" in app,
 "go_offer_asset":"go-offer.svg" in app,
 "same_brand_box":app.count("class=\"go-feature-brand")>=2,
 "offer_namespace_isolated":"go-feature-brand go-offer-brand" in app and "go-feature-brand offer" not in app,
 "no_offer_transform":not re.search(r"go-offer-brand\s*\{[^}]*transform\s*:\s*(?!none)",css,re.S),
 "native_header_geometry":"width:257px;height:61px" in css,
 "native_feature_geometry":"height:24.5px!important" in css,
 "reference_card_artwork":all(x in css for x in ("kyoto-reference10.jpg","maldives-reference10.jpg","lisbon-reference10.jpg")),
 "single_badge_dom":app.count("<span class=\"go-reco-badge\">GO 推荐</span>")==3,
 "bottom_safe_area":"env(safe-area-inset-bottom)" in css,
 "375_breakpoint":"max-width:389px" in css and "max-width:375px" in css,
 "430_breakpoint":"min-width:406px" in css,
}
failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(f"{k}={'PASS' if v else 'FAIL'}")
if failed: block("FAILED:"+",".join(failed))
print("R8.2_CONSUMER_VI_REFERENCE10_GATE: PASS")
