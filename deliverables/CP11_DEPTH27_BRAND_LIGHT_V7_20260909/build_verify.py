"""Generate a lighter GO logo preview from the preserved V6 vector.

The G/O geometry is edited directly. English uses outlined Nimbus Sans Regular
with a controlled stroke for an intermediate weight; no runtime font is needed.
"""
from pathlib import Path
import copy
import hashlib
import json
import math
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.svgLib.path import parse_path
from PIL import Image

ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent/'go-brand-master-v6-20260909/source_changes/frontend/consumer/assets/go-main-lockup-master-v6.svg'
data = PARENT.read_bytes()
assert hashlib.sha256(data).hexdigest() == '58d357699590f2bf4fa7934c72e0f97ded265be184d16bdcaf5d492188928953'
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
tag = lambda n: '{'+NS+'}'+n
svg = ET.fromstring(data)
base = copy.deepcopy(svg)
get = lambda tree, identity: tree.find(f".//*[@id='{identity}']")
def bounds(p):
    pen = BoundsPen(None)
    parse_path(p.get('d'), pen)
    return pen.bounds
def transform(p, s, x, y):
    p.set('transform', f'matrix({s:.12f} 0 0 {s:.12f} {x:.12f} {y:.12f})')

# Slightly thinner ring: 185 -> 165 units, preserving the 1000-unit outer diameter.
mark = get(svg, 'go-mark')
g, bar, o, connector = list(mark)
gx = 500 + 335 * (914.519-500)/500
gy = 500 + 335 * (220.404-500)/500
g.set('d', f'M914.519 220.404 A500 500 0 1 0 1000 500 L835 500 A335 335 0 1 1 {gx:.6f} {gy:.6f} Z')
bar.set('d', 'M600 425 H1030 V575 H470 Z')
inner_x = 1550 - math.sqrt(335**2-100**2)
o.set('d', f'M1060.102051 400 A500 500 0 1 1 1060.102051 600 L{inner_x:.9f} 600 A335 335 0 1 0 {inner_x:.9f} 400 Z')
mark.set('data-go-mark', 'equal-circles-lighter-v7')
assert ET.tostring(connector) == ET.tostring(list(get(base,'go-mark'))[3])

# Use an outlined intermediate English weight and retain V6's word gap and width.
font_path = Path('/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf')
font = TTFont(font_path)
glyphs = font.getGlyphSet()
row = get(svg, 'english-line')
row.attrib.pop('transform', None)
word = get(svg, 'wordmark')
word.clear()
word.attrib.update({'id':'wordmark', 'data-wordmark':'AI DIRECT', 'fill':'#061B3A',
                    'stroke':'#061B3A', 'stroke-width':'24', 'stroke-linejoin':'round'})
english = []
for i, ch in enumerate('AIDIRECT'):
    pen = SVGPathPen(glyphs)
    glyphs[font.getBestCmap()[ord(ch)]].draw(TransformPen(pen, (1,0,0,-1,0,0)))
    p = ET.SubElement(word, tag('path'), {'id':f'english-{i}', 'data-character':ch, 'd':pen.getCommands()})
    english.append(p)
stroke = 24.0
eb = [bounds(p) for p in english]
top = min(b[1] for b in eb)-stroke/2
bottom = max(b[3] for b in eb)+stroke/2
es = 500/(bottom-top)
widths = [(b[2]-b[0]+stroke)*es for b in eb]
weights = [1,.95,.95,.9,.9,.85]
unit = (3370-sum(widths)-270)/sum(weights)
gaps = [unit,270,.95*unit,.95*unit,.9*unit,.9*unit,.85*unit]
x = 2470.0
for i,(p,b,w) in enumerate(zip(english,eb,widths)):
    transform(p, es, x-es*(b[0]-stroke/2), -es*top)
    x += w + (gaps[i] if i < 7 else 0)
assert abs(x-5840) < 1e-7
plus = get(svg, 'plus')
pb = bounds(plus)
ps = 200/(pb[2]-pb[0])
t_top = es*(eb[7][1]-stroke/2-top)
transform(plus, ps, 5910-ps*pb[0], t_top-ps*pb[1])

# Chinese is reduced only slightly; original outlines are preserved in full.
cn = get(svg, 'chinese-line')
cn.set('stroke-width', '1.4')
cn.set('data-subtitle', 'outlined-lighter-v7')
cb = [bounds(p) for p in cn]
csw = 1.4
ctop = min(b[1] for b in cb)-csw/2
cbottom = max(b[3] for b in cb)+csw/2
cs = 280/(cbottom-ctop)
cw = [(b[2]-b[0]+csw)*cs for b in cb]
cgap = (3640-sum(cw)-75)/11
x = 2470.0
for i,(p,b,w) in enumerate(zip(cn,cb,cw)):
    assert p.get('d') == list(get(base,'chinese-line'))[i].get('d')
    transform(p, cs, x-cs*(b[0]-csw/2), 720-cs*ctop)
    x += w+(cgap if i<11 else 0)+(75 if i==4 else 0)
assert abs(x-6110) < 1e-7
assert ''.join(p.get('data-character') for p in cn) == '发现全世界直接向官方预订'
svg.set('id','go-lockup-lighter-v7')
svg.find(tag('title')).text = 'GO AI DIRECT+ — lighter mark and bilingual lettering'
get(svg,'right-block').set('data-right-block','lighter-v7')
assert ET.tostring(get(svg,'divider')) == ET.tostring(get(base,'divider'))
asset = ROOT/'GO_LIGHTER_V7.svg'
asset.write_bytes(ET.tostring(svg,encoding='utf-8',xml_declaration=True))
q = subprocess.run(['inkscape',str(asset),'--query-all'],check=True,capture_output=True,text=True)
m = {}
for line in q.stdout.splitlines():
    p = line.split(',')
    if len(p)==5:
        m[p[0]] = [float(v) for v in p[1:]]
def near(a,b):
    assert abs(a-b)<.03,(a,b)
near(m['plus'][1],m['english-7'][1])
for index in [0,2]:
    near(m['english-line'][index],m['chinese-line'][index])
for index in [1,3]:
    near(m['go-mark'][index],m['right-block'][index])
assert m['plus'][2:] == [200,200]
last = m['chinese-11']
assert last[0]+last[2]<6590 and last[1]+last[3]<1240
renders = []
for width,name in [(1600,'GO_LIGHTER_V7.png'),(320,'GO_LIGHTER_V7_320.png')]:
    dest = ROOT/name
    subprocess.run(['inkscape',str(asset),'--export-type=png',f'--export-filename={dest}',
                    f'--export-width={width}','--export-background=white'],check=True,capture_output=True)
    im=Image.open(dest).convert('RGB')
    ink=im.convert('L').point(lambda v:255 if v<220 else 0).getbbox()
    assert ink[0]>0 and ink[1]>0 and ink[2]<im.width and ink[3]<im.height
    renders.append({'file':name,'size_px':im.size,'ink_bounds_px':ink})
record = {
    'created_at_utc':datetime.now(timezone.utc).isoformat(),
    'parent_commit':'59136e8888ea7d2d752ea4ff77675b832a267d0c',
    'parent_svg_sha256':hashlib.sha256(data).hexdigest(),
    'svg_sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),
    'font_source':'Nimbus Sans Regular, outlined with 24 font-unit same-color stroke',
    'font_sha256':hashlib.sha256(font_path.read_bytes()).hexdigest(),
    'G_O_ring_width':{'before':185,'after':165},
    'G_bar_height':{'before':160,'after':150},
    'English_I_visible_stem':{'before':98.1675,'after':m['english-1'][2]},
    'Chinese_stroke_width':{'before':2.4,'after':1.4},
    'constraints':{'G_O_outer_diameter_preserved':True,'red_connector_preserved':True,
                   'plus_size_preserved_and_top_aligned_with_T':True,
                   'English_Chinese_visible_line_edges_aligned':True,
                   'GO_and_bilingual_block_equal_height':True,'final_ding_complete':True},
    'bounds_page_xywh':{k:m[k] for k in ['go-mark','right-block','english-line','chinese-line','english-7','plus','chinese-11']},
    'render_checks':renders,
    'scope':'Design preview only. No application code, deployment or release gate changes.',
}
(ROOT/'DESIGN_VERIFIED.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(record,ensure_ascii=False,indent=2))
