"""Align existing SVG outlines without editing any sealed source or evidence."""
from pathlib import Path
import copy
import hashlib
import json
import math
import re
import subprocess
import xml.etree.ElementTree as ET

import fitz
from PIL import Image
from fontTools.pens.boundsPen import BoundsPen
from fontTools.svgLib.path import parse_path

ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent / 'go-brand-text-safe-20260909/source_changes/frontend/consumer'
OUT = ROOT / 'source_changes/frontend/consumer'
OUT.joinpath('assets').mkdir(parents=True, exist_ok=True)
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
tag = lambda n: '{' + NS + '}' + n
sha = lambda b: hashlib.sha256(b).hexdigest()
original = (PARENT / 'assets/go-main-lockup.svg').read_bytes()
assert sha(original) == '24c2830d56cc2394993f7eb30d05f831f2043f9015c27f597c1f62eb14dd1672'
svg = ET.fromstring(original)
right = svg.find(".//*[@data-right-block]")
word = svg.find(".//*[@data-wordmark]")
plus = svg.find(".//*[@data-plus]")
subtitle = svg.find(".//*[@data-subtitle]")
mark = svg.find(".//*[@data-go-mark]")
untouched = {k: ET.tostring(v) for k, v in [('mark', mark), ('plus', plus), ('word', word)]}
subtitle_paths = [p.get('d') for p in subtitle]

def bounds(nodes):
    pen = BoundsPen(None)
    for node in nodes:
        for path in node.iter(tag('path')):
            parse_path(path.get('d'), pen)
    return pen.bounds

ex0, ey0, ex1, ey1 = bounds([word, plus])
cx0, cy0, cx1, cy1 = bounds([subtitle])
subtitle_scale = (ex1-ex0)/(cx1-cx0)
# Uniform scaling preserves the shape and proportions of every Chinese glyph.
# Keep the bottom edge; the upper English line and + are not altered.
subtitle.set('transform', f'matrix({subtitle_scale:.15f} 0 0 {subtitle_scale:.15f} {ex0-subtitle_scale*cx0:.15f} {cy1-subtitle_scale*cy1:.15f})')
subtitle.set('id', 'chinese-line')
chars = '发现全世界直接向官方预订'
assert len(subtitle) == len(chars)
for i, (path, char) in enumerate(zip(subtitle, chars)):
    path.set('id', f'glyph-{i}')
    path.set('data-character', char)
assert subtitle[-1].get('data-character') == '订'

english = ET.Element(tag('g'), {'id': 'english-line'})
right.remove(word)
right.remove(plus)
english.extend([word, plus])
right.insert(0, english)
scale = 1000/(cy1-ey0)
left = 2470
right.set('transform', f'matrix({scale:.15f} 0 0 {scale:.15f} {left-scale*ex0:.15f} {-scale*ey0:.15f})')
right.set('data-right-block', 'equal-height-aligned-lines-v3')
right.set('id', 'right-block')
mark.set('id', 'go-mark')
right_edge = left + (ex1-ex0)*scale
# Symmetric breathing room protects both left/right and top/bottom artwork.
margin_x, margin_y = 240, 120
view_width = math.ceil(right_edge + 2*margin_x)
svg.set('viewBox', f'{-margin_x} {-margin_y} {view_width} {1000+2*margin_y}')
svg.set('preserveAspectRatio', 'xMidYMid meet')
svg.set('id', 'go-lockup-aligned-v3')
svg.find(tag('title')).text = 'GO AI DIRECT+ — aligned English and Chinese with full final character'
data = ET.tostring(svg, encoding='utf-8', xml_declaration=True)
for name in ['go-main-lockup.svg', 'go-main-lockup-aligned-v3.svg']:
    (OUT / 'assets' / name).write_bytes(data)

app_bytes = (PARENT / 'app.js').read_bytes()
assert sha(app_bytes) == '68c17c1b0e56e491fdf14809ab3586bda65a830502844314f492dd17b17435a7'
app = app_bytes.decode()
old = 'go-main-lockup.svg?v=20260909-text-safe'
new = 'go-main-lockup-aligned-v3.svg?v=20260909-aligned-v3'
assert app.count(old) == 1
(OUT / 'app.js').write_text(app.replace(old, new))

# Verify unchanged components, including both portions of the last character.
mark_no_id = copy.deepcopy(mark)
mark_no_id.attrib.pop('id')
assert ET.tostring(mark_no_id) == untouched['mark']
assert ET.tostring(word) == untouched['word']
assert ET.tostring(plus) == untouched['plus']
assert [p.get('d') for p in subtitle] == subtitle_paths
last_d = subtitle[-1].get('d')
assert len(re.findall(r'[Mm]', last_d)) == 3

asset = OUT / 'assets/go-main-lockup-aligned-v3.svg'
# Obtain independent transformed geometry from Inkscape, not the layout math.
query = subprocess.run(['inkscape', str(asset), '--query-all'], check=True, capture_output=True, text=True)
measured = {}
for line in query.stdout.splitlines():
    fields = line.split(',')
    if len(fields) == 5:
        measured[fields[0]] = [float(x) for x in fields[1:]]
e, c = measured['english-line'], measured['chinese-line']
g, r = measured['go-mark'], measured['right-block']
last = measured['glyph-11']
assert abs(e[0]-c[0]) < .02
assert abs((e[0]+e[2])-(c[0]+c[2])) < .02
assert abs(g[1]-r[1]) < .02
assert abs((g[1]+g[3])-(r[1]+r[3])) < .02
# Inkscape reports page coordinates (including the viewBox-origin offset).
assert last[0]+last[2] <= view_width-margin_x+.02

# Render the full canvas using two independent SVG renderers.
preview = ROOT / 'GO_ALIGNED_V3.png'
subprocess.run(['inkscape', str(asset), '--export-type=png', f'--export-filename={preview}', '--export-width=1600', '--export-background=white'], check=True, capture_output=True)
with fitz.open(stream=data, filetype='svg') as doc:
    pdf_data = doc.convert_to_pdf()
with fitz.open(stream=pdf_data, filetype='pdf') as doc:
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(1600/doc[0].rect.width,1600/doc[0].rect.width), alpha=False)
    pix.save(ROOT / 'GO_ALIGNED_V3_SECOND_RENDERER.png')

render_checks = {}
for path in [preview, ROOT / 'GO_ALIGNED_V3_SECOND_RENDERER.png']:
    im = Image.open(path).convert('RGB')
    mask = im.convert('L').point(lambda x: 255 if x < 220 else 0)
    box = mask.getbbox()
    assert box and box[0] >= 40 and im.width-box[2] >= 40
    assert box[1] >= 20 and im.height-box[3] >= 20
    render_checks[path.name] = {'pixels': im.size, 'ink_bbox': box, 'right_blank_pixels': im.width-box[2]}

record = {
    'parent_commit': '70ecfed649fad32cc7435506101380598843dbb6',
    'scope': 'Brand vector source and one consumer-header asset reference only.',
    'source_svg_sha256': sha(original),
    'new_svg_sha256': sha(data),
    'english_includes_plus': True,
    'subtitle_scale_is_uniform': True,
    'subtitle_scale': subtitle_scale,
    'english_ink_bounds_xywh': e,
    'measured_bounds_space': 'Inkscape page coordinates, including viewBox-origin offset',
    'chinese_ink_bounds_xywh': c,
    'left_and_right_edges_match': True,
    'go_ink_bounds_xywh': g,
    'right_block_ink_bounds_xywh': r,
    'left_right_top_and_bottom_match': True,
    'final_character': '订',
    'final_character_ink_bounds_xywh': last,
    'all_12_glyph_outlines_preserved': True,
    'last_character_all_3_subpaths_preserved': True,
    'go_red_connector_and_english_plus_geometry_preserved': True,
    'viewBox': svg.get('viewBox'),
    'renderer_checks': render_checks,
    'new_asset_filename_avoids_old_url_cache': True,
    'limitations': ['Static vector geometry and rendered PNG verification only.', 'No actual user-device or browser/container verification.', 'No business tests rerun, Hong Kong deployment, or release-gate change.'],
}
(ROOT / 'ALIGNMENT_VERIFIED.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(record, ensure_ascii=False, indent=2))
