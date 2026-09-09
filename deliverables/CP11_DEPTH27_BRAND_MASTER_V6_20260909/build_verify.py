"""Refine the approved GO vector and derive a compact header asset.

No source glyph is redrawn. Requires the preserved V5 package alongside this
directory, Python fontTools/Pillow/PyMuPDF, and Inkscape.
"""
from pathlib import Path
import copy
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from fontTools.pens.boundsPen import BoundsPen
from fontTools.svgLib.path import parse_path
from PIL import Image
import fitz

ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent / 'go-brand-plus-top-v5-20260909/source_changes/frontend/consumer'
OUT = ROOT / 'source_changes/frontend/consumer'
ASSETS = OUT / 'assets'
ASSETS.mkdir(parents=True, exist_ok=True)
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
tag = lambda name: '{' + NS + '}' + name
sha = lambda data: hashlib.sha256(data).hexdigest()
source = (PARENT / 'assets/go-main-lockup-plus-top-v5.svg').read_bytes()
assert sha(source) == '7c6ca5836331b71f20e0e09e19ac4884f41b615f86d3e2653434c67563b2655f'
base = ET.fromstring(source)
master = copy.deepcopy(base)

def get(svg, identity):
    return svg.find(f".//*[@id='{identity}']")

def raw_bounds(path):
    pen = BoundsPen(None)
    parse_path(path.get('d'), pen)
    return pen.bounds

def matrix(path):
    return [float(x) for x in re.fullmatch(r'matrix\(([^)]+)\)', path.get('transform')).group(1).split()]

def set_matrix(path, values):
    path.set('transform', 'matrix(' + ' '.join(f'{v:.12f}' for v in values) + ')')

def save(svg, filename):
    destination = ASSETS / filename
    destination.write_bytes(ET.tostring(svg, encoding='utf-8', xml_declaration=True))
    return destination

# Only horizontal translation changes: allocate more space to the word boundary
# and proportionally tighten the existing six letter-pair gaps.
letters = [get(master, f'english-{i}') for i in range(8)]
scale = matrix(letters[0])[0]
widths = [(raw_bounds(p)[2] - raw_bounds(p)[0]) * scale for p in letters]
word_gap = 270.0
weights = [1.0, .95, .95, .9, .9, .85]
letter_space = 3370.0 - sum(widths) - word_gap
unit = letter_space / sum(weights)
gaps = [unit, word_gap, .95*unit, .95*unit, .9*unit, .9*unit, .85*unit]
x = 2470.0
for i, p in enumerate(letters):
    m = matrix(p)
    m[4] = x - scale * raw_bounds(p)[0]
    set_matrix(p, m)
    x += widths[i] + (gaps[i] if i < 7 else 0)
assert abs(x - 5840) < 1e-7
master.set('id', 'go-lockup-master-v6')
master.find(tag('title')).text = 'GO AI DIRECT+ — full bilingual master'
get(master, 'right-block').set('data-right-block', 'master-v6')
for identity in ['go-mark', 'divider', 'chinese-line', 'plus']:
    assert ET.tostring(get(master, identity)) == ET.tostring(get(base, identity))
for old, new in zip(get(base, 'wordmark'), letters):
    assert old.get('d') == new.get('d')
    assert matrix(old)[:4] == matrix(new)[:4]
    assert matrix(old)[5] == matrix(new)[5]
assert ''.join(p.get('data-character') for p in get(master, 'chinese-line')) == '发现全世界直接向官方预订'
assert not list(master.iter(tag('text')))
main_path = save(master, 'go-main-lockup-master-v6.svg')
save(master, 'go-main-lockup.svg')

# Compact header: preserve the mark and wordmark, and use a single English line.
# The full bilingual master remains the primary asset. Letterforms are uniformly
# scaled, centered vertically with the GO mark, and never horizontally distorted.
compact = ET.Element(tag('svg'), {
    'id': 'go-lockup-compact-v6', 'preserveAspectRatio': 'xMidYMid meet',
    'role': 'img', 'aria-label': 'GO AI DIRECT+',
})
ET.SubElement(compact, tag('title')).text = 'GO AI DIRECT+ — compact header'
compact.append(copy.deepcopy(get(base, 'go-mark')))
row = ET.SubElement(compact, tag('g'), {'id': 'english-line', 'fill': '#061B3A'})
compact_scale = 650.0 / (475.865 - 281.045)
compact_gaps = [64.0, 240.0, 64.0, 64.0, 58.0, 58.0, 52.0]
cx = 2350.0
for i, original in enumerate(letters):
    p = copy.deepcopy(original)
    b = raw_bounds(p)
    set_matrix(p, [compact_scale, 0, 0, compact_scale,
                   cx - compact_scale*b[0], 175.0 - compact_scale*281.045])
    row.append(p)
    cx += compact_scale * (b[2]-b[0]) + (compact_gaps[i] if i < 7 else 0)
p = copy.deepcopy(get(base, 'plus'))
pb = raw_bounds(p)
t_top = 175.0 + compact_scale * (raw_bounds(letters[7])[1] - 281.045)
ps = 260.0 / (pb[2]-pb[0])
set_matrix(p, [ps, 0, 0, ps, cx+90.0-ps*pb[0], t_top-ps*pb[1]])
row.append(p)
compact_width = cx + 90 + 260 + 320
compact.set('viewBox', f'-160 -120 {compact_width:.12f} 1240')
compact_path = save(compact, 'go-compact-lockup-v6.svg')

mark = ET.Element(tag('svg'), {
    'id': 'go-mark-v6', 'viewBox': '-160 -120 2370 1240',
    'preserveAspectRatio': 'xMidYMid meet', 'role': 'img', 'aria-label': 'GO',
})
ET.SubElement(mark, tag('title')).text = 'GO — small mark'
mark.append(copy.deepcopy(get(base, 'go-mark')))
mark_path = save(mark, 'go-mark-v6.svg')

# Prepare the consumer source patch; this package does not update a live site.
app = (PARENT / 'app.js').read_bytes()
assert sha(app) == 'c893974a0d8ddd4984efca1580ec5ff480141b8698ac4fe46f7587d4ee73583f'
old_ref = b'go-main-lockup-plus-top-v5.svg?v=20260909-plus-top-v5'
new_ref = b'go-main-lockup-master-v6.svg?v=20260909-master-v6'
assert app.count(old_ref) == 1
(OUT / 'app.js').write_bytes(app.replace(old_ref, new_ref))

def query(path):
    result = subprocess.run(['inkscape', str(path), '--query-all'],
                            check=True, capture_output=True, text=True)
    bounds = {}
    for line in result.stdout.splitlines():
        fields = line.split(',')
        if len(fields) == 5:
            bounds[fields[0]] = [float(n) for n in fields[1:]]
    return bounds

def near(a, b):
    assert abs(a-b) < .02, (a, b)

mb = query(main_path)
cb = query(compact_path)
for key in [mb, cb]:
    near(key['plus'][1], key['english-7'][1])
e, c, g, r = [mb[k] for k in ['english-line', 'chinese-line', 'go-mark', 'right-block']]
near(e[0], c[0])
near(e[2], c[2])
near(g[1], r[1])
near(g[3], r[3])
near(mb['english-2'][0] - sum([mb['english-1'][0], mb['english-1'][2]]), word_gap)
assert mb['plus'][2:] == [200, 200]
last = mb['chinese-11']
assert last[0] > 0 and last[1] > 0 and last[0]+last[2] < 6590 and last[1]+last[3] < 1240

render_checks = []
def render(path, width, filename, engine='inkscape'):
    dest = ROOT / filename
    if engine == 'inkscape':
        subprocess.run(['inkscape', str(path), '--export-type=png',
                        '--export-filename='+str(dest), '--export-width='+str(width),
                        '--export-background=white'], check=True, capture_output=True)
    else:
        with fitz.open(stream=path.read_bytes(), filetype='svg') as document:
            pdf = document.convert_to_pdf()
        with fitz.open(stream=pdf, filetype='pdf') as document:
            s = width / document[0].rect.width
            document[0].get_pixmap(matrix=fitz.Matrix(s, s), alpha=False).save(dest)
    im = Image.open(dest).convert('RGB')
    ink = im.convert('L').point(lambda v: 255 if v < 220 else 0).getbbox()
    assert ink and ink[0] > 0 and ink[1] > 0 and ink[2] < im.width and ink[3] < im.height
    render_checks.append({'file': filename, 'engine': engine, 'size_px': im.size,
                          'ink_bounds_px': ink, 'canvas_clipping': False})

render(main_path, 1600, 'GO_MASTER_V6.png')
render(compact_path, 1200, 'GO_COMPACT_V6.png')
render(main_path, 320, 'GO_MASTER_320.png')
render(compact_path, 160, 'GO_COMPACT_160.png')
render(compact_path, 200, 'GO_COMPACT_200.png')
render(mark_path, 32, 'GO_MARK_32.png')
render(main_path, 320, 'GO_MASTER_320_MUPDF.png', 'mupdf')
render(compact_path, 160, 'GO_COMPACT_160_MUPDF.png', 'mupdf')

# An exact-scale proof sheet uses nested source SVGs, without raster upscaling.
sheet = ET.Element(tag('svg'), {'viewBox': '0 0 920 580', 'width': '920', 'height': '580'})
ET.SubElement(sheet, tag('rect'), {'width': '920', 'height': '580', 'fill': '#F4F6F9'})
def label(x, y, content, size=14, fill='#536175'):
    ET.SubElement(sheet, tag('text'), {'x': str(x), 'y': str(y), 'font-family': 'sans-serif',
                 'font-size': str(size), 'fill': fill}).text = content
def sample(svg, x, y, width, height):
    s = copy.deepcopy(svg)
    s.set('x', str(x)); s.set('y', str(y)); s.set('width', str(width)); s.set('height', str(height))
    ET.SubElement(sheet, tag('rect'), {'x': str(x-12), 'y': str(y-12),
                   'width': str(width+24), 'height': str(height+24), 'rx': '8', 'fill': 'white'})
    sheet.append(s)
label(40, 40, 'GO / BRAND APPLICATION PROOF', 18, '#061B3A')
label(40, 73, 'Full bilingual master')
sample(master, 40, 95, 820, 820*1240/6590)
label(40, 295, 'Full master / 320 px')
sample(master, 40, 319, 320, 320*1240/6590)
label(440, 295, 'Compact header / 200 px')
sample(compact, 440, 327, 200, 200*1240/compact_width)
label(40, 448, 'Compact header / 160 px')
sample(compact, 40, 479, 160, 160*1240/compact_width)
label(440, 448, 'Mark / 32 px')
sample(mark, 440, 484, 32, 32*1240/2370)
label(40, 557, 'Static vector proof at 1x. Select by allocated logo width; keep the native aspect ratio.', 12)
sheet_path = ROOT / 'GO_APPLICATION_PROOF.svg'
sheet_path.write_bytes(ET.tostring(sheet, encoding='utf-8', xml_declaration=True))
render(sheet_path, 920, 'GO_APPLICATION_PROOF.png')

record = {
    'verified_at_utc': datetime.now(timezone.utc).isoformat(),
    'parent_commit': '9113662a85a14ff9783fdd7708c02a3f4b682693',
    'parent_svg_sha256': sha(source), 'master_svg_sha256': sha(main_path.read_bytes()),
    'master_english_word_gap': {'before': 200, 'after': word_gap},
    'master_letter_gaps': gaps,
    'verified_constraints': {
        'G_O_and_red_connector_preserved': True,
        'left_GO_and_right_bilingual_block_equal_height': True,
        'English_including_plus_and_Chinese_equal_visible_width': True,
        'plus_top_equals_T_top_in_master_and_compact': True,
        'all_Chinese_outlines_preserved_including_final_ding': True,
        'no_font_dependency_or_glyph_squeezing': True,
    },
    'master_bounds_page_xywh': {k: mb[k] for k in ['go-mark','right-block','english-line','chinese-line','english-1','english-2','english-7','plus','chinese-11']},
    'compact_bounds_page_xywh': {k: cb[k] for k in ['go-mark','english-line','english-7','plus']},
    'recommended_allocated_width_px': {'bilingual_master': '>=320', 'compact': '160–319', 'mark': '32–159'},
    'render_checks': render_checks,
    'scope': 'Static vector geometry and raster proof only. No real-device/browser, Hong Kong deployment or release-gate verification. Compact selection is supplied as an asset specification, not integrated into a running header.',
}
(ROOT / 'DESIGN_VERIFIED.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({'master_gap': word_gap, 'compact_viewbox_width': compact_width,
                  'rendered': len(render_checks), 'constraints': record['verified_constraints']}, ensure_ascii=False, indent=2))
