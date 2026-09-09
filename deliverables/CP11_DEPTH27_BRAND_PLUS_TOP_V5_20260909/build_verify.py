"""Align the red plus to T's visible top; preserve the approved vector system."""
from pathlib import Path
import copy
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from fontTools.pens.boundsPen import BoundsPen
from fontTools.svgLib.path import parse_path

ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent/'go-brand-refined-v4-20260909/source_changes/frontend/consumer'
OUT = ROOT/'source_changes/frontend/consumer'
(OUT/'assets').mkdir(parents=True, exist_ok=True)
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
tag = lambda name: '{'+NS+'}'+name
sha = lambda data: hashlib.sha256(data).hexdigest()
original = (PARENT/'assets/go-main-lockup-refined-v4.svg').read_bytes()
assert sha(original) == 'b838793ce832012d78e686b906f94bb3d994af24a802232a7dfcb366a8f7306f'
svg = ET.fromstring(original)
baseline = copy.deepcopy(svg)
english = svg.find(".//*[@id='english-line']")
plus = svg.find(".//*[@id='plus']")
t = svg.find(".//*[@id='english-7']")
assert t.get('data-character') == 'T'

def matrix(path):
    values = re.fullmatch(r'matrix\(([^)]+)\)', path.get('transform')).group(1)
    return [float(v) for v in values.split()]

def drawn_bounds(path):
    pen = BoundsPen(None)
    parse_path(path.get('d'), pen)
    a,b,c,d,e,f = matrix(path)
    assert b == c == 0 and a == d and a > 0
    x0,y0,x1,y1 = pen.bounds
    return (a*x0+e,d*y0+f,a*x1+e,d*y1+f)

t_top = drawn_bounds(t)[1]
plus_top = drawn_bounds(plus)[1]
delta = t_top-plus_top
m = matrix(plus)
m[5] += delta
plus.set('transform', 'matrix('+' '.join(f'{v:.12f}' for v in m)+')')
# After removing the overhanging plus, normalize only the English row upward.
# The Chinese row, mark, divider, x positions and both line widths stay unchanged.
row_top = min(drawn_bounds(p)[1] for p in english.iter(tag('path')))
english.set('transform', f'translate(0 {-row_top:.12f})')
svg.set('id', 'go-lockup-plus-top-v5')
svg.find(tag('title')).text = 'GO AI DIRECT+ — red plus top aligned with T'
svg.find(".//*[@id='right-block']").set('data-right-block','plus-top-v5')
data = ET.tostring(svg, encoding='utf-8', xml_declaration=True)
for name in ['go-main-lockup.svg','go-main-lockup-plus-top-v5.svg']:
    (OUT/'assets'/name).write_bytes(data)
for identity in ['go-mark','divider','chinese-line','wordmark']:
    assert ET.tostring(svg.find(f".//*[@id='{identity}']")) == ET.tostring(baseline.find(f".//*[@id='{identity}']"))
assert plus.get('d') == baseline.find(".//*[@id='plus']").get('d')

app_data = (PARENT/'app.js').read_bytes()
assert sha(app_data) == 'bf695fa0321e5d0d1ec24e97036ad1f1d34756f52c1e4bb5ad1807ff6385fbd1'
app = app_data.decode()
old = 'go-main-lockup-refined-v4.svg?v=20260909-refined-v4'
new = 'go-main-lockup-plus-top-v5.svg?v=20260909-plus-top-v5'
assert app.count(old) == 1
(OUT/'app.js').write_text(app.replace(old,new))
asset = OUT/'assets/go-main-lockup-plus-top-v5.svg'
query = subprocess.run(['inkscape',str(asset),'--query-all'],check=True,capture_output=True,text=True)
measured = {}
for line in query.stdout.splitlines():
    parts = line.split(',')
    if len(parts) == 5:
        measured[parts[0]] = [float(v) for v in parts[1:]]
assert abs(measured['plus'][1]-measured['english-7'][1]) < .01
e,c,g,r = [measured[k] for k in ['english-line','chinese-line','go-mark','right-block']]
assert abs(e[0]-c[0]) < .01 and abs(e[2]-c[2]) < .01
assert abs(g[1]-r[1]) < .01 and abs(g[3]-r[3]) < .01
assert measured['plus'][2:] == [200.0,200.0]
subprocess.run(['inkscape',str(asset),'--export-type=png',f'--export-filename={ROOT / "GO_PLUS_TOP_V5.png"}','--export-width=1600','--export-background=white'],check=True,capture_output=True)
record = {
    'parent_commit':'db4864f158876baa0a0189ff48bd24bf2aa496c5',
    'parent_svg_sha256':sha(original),'new_svg_sha256':sha(data),
    'red_plus_top_matches_T_top':True,
    'plus_bounds_page_xywh':measured['plus'],'T_bounds_page_xywh':measured['english-7'],
    'plus_relative_downward_shift':delta,'english_row_upward_shift':row_top,
    'equal_line_widths_preserved':True,'left_right_equal_height_preserved':True,
    'unchanged':['G/O and central red block','all glyph outlines','Chinese row position and weight','English horizontal spacing','plus size and horizontal position','divider and canvas safe margins'],
    'validation':'Static SVG and rendered PNG only; no browser/Hong Kong or release-gate claim.',
}
(ROOT/'ALIGNMENT_VERIFIED.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(record,ensure_ascii=False,indent=2))
