"""Deterministic refinement of the approved GO vector lockup; never edits parents."""
from pathlib import Path
import copy
import hashlib
import json
import math
import subprocess
import xml.etree.ElementTree as ET

import fitz
from fontTools.pens.boundsPen import BoundsPen
from fontTools.svgLib.path import parse_path
from PIL import Image

ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent / 'go-brand-aligned-v3-20260909/source_changes/frontend/consumer'
OUT = ROOT / 'source_changes/frontend/consumer'
ASSETS = OUT / 'assets'
ASSETS.mkdir(parents=True, exist_ok=True)
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
tag = lambda n: '{' + NS + '}' + n
digest = lambda b: hashlib.sha256(b).hexdigest()
original = (PARENT / 'assets/go-main-lockup-aligned-v3.svg').read_bytes()
assert digest(original) == '87710c03858f7caba0d3a08761cb1aef9fe31702350ca69fd92235dc053ef186'
parent = ET.fromstring(original)

def path_bounds(path):
    pen = BoundsPen(None)
    parse_path(path.get('d'), pen)
    return pen.bounds

def union(boxes):
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)

def matrix(s, x, y):
    return f'matrix({s:.12f} 0 0 {s:.12f} {x:.12f} {y:.12f})'

LEFT = 2470.0
WIDTH = 3640.0
MARGIN_X = 240
MARGIN_Y = 120
VIEW_WIDTH = int(LEFT + WIDTH + 2*MARGIN_X)
VIEW_HEIGHT = 1000 + 2*MARGIN_Y
svg = ET.Element(tag('svg'), {
    'viewBox': f'{-MARGIN_X} {-MARGIN_Y} {VIEW_WIDTH} {VIEW_HEIGHT}',
    'preserveAspectRatio': 'xMidYMid meet',
    'role': 'img',
    'aria-label': 'GO AI DIRECT+ 发现全世界 直接向官方预订',
    'id': 'go-lockup-refined-v4',
})
ET.SubElement(svg, tag('title')).text = 'GO AI DIRECT+ — refined equal-height bilingual lockup'
mark = copy.deepcopy(parent.find(".//*[@data-go-mark]"))
svg.append(mark)
divider = ET.SubElement(svg, tag('line'), {
    'id': 'divider', 'x1': '2260', 'x2': '2260', 'y1': '220', 'y2': '780',
    'stroke': '#061B3A', 'stroke-opacity': '.28', 'stroke-width': '12',
})
right = ET.SubElement(svg, tag('g'), {'id': 'right-block', 'data-right-block': 'refined-v4'})
english = ET.SubElement(right, tag('g'), {'id': 'english-line', 'fill': '#061B3A'})
word = ET.SubElement(english, tag('g'), {'id': 'wordmark', 'data-wordmark': 'AI DIRECT'})
old_letters = list(parent.find(".//*[@data-wordmark]"))
eb = union([path_bounds(p) for p in old_letters])
en_scale = 500/(eb[3]-eb[1])
glyph_widths = [(path_bounds(p)[2]-path_bounds(p)[0])*en_scale for p in old_letters]
plus_size, plus_gap, word_gap = 200.0, 70.0, 200.0
gap_budget = WIDTH-sum(glyph_widths)-plus_size-plus_gap-word_gap
# Pair-specific optical spacing; the one word space remains clearly distinct.
weights = [1.0, None, .95, .95, .9, .9, .85]
weight_total = sum(w for w in weights if w is not None)
gaps = [word_gap if w is None else gap_budget*w/weight_total for w in weights]
x = LEFT
for i, (src, char) in enumerate(zip(old_letters, 'AIDIRECT')):
    b = path_bounds(src)
    glyph = copy.deepcopy(src)
    glyph.set('id', f'english-{i}')
    glyph.set('data-character', char)
    glyph.set('transform', matrix(en_scale, x-en_scale*b[0], 60-en_scale*eb[1]))
    word.append(glyph)
    x += glyph_widths[i] + (gaps[i] if i < len(gaps) else 0)

plus = copy.deepcopy(parent.find(".//*[@data-plus]"))
pb = path_bounds(plus)
ps = plus_size/(pb[2]-pb[0])
plus.set('id', 'plus')
plus.set('transform', matrix(ps, LEFT+WIDTH-plus_size-ps*pb[0], -ps*pb[1]))
english.append(plus)
assert abs(x+plus_gap+plus_size-(LEFT+WIDTH)) < 1e-7

chinese = ET.SubElement(right, tag('g'), {
    'id': 'chinese-line', 'data-subtitle': 'outlined-refined',
    'fill': '#061B3A', 'stroke': '#061B3A', 'stroke-width': '2.4',
    'stroke-linejoin': 'round', 'stroke-linecap': 'round',
})
old_chinese = list(parent.find(".//*[@data-subtitle]"))
chars = '发现全世界直接向官方预订'
assert len(old_chinese) == len(chars)
cb = union([path_bounds(p) for p in old_chinese])
stroke = 2.4
zh_scale = 280/(cb[3]-cb[1]+stroke)
chinese_widths = [(path_bounds(p)[2]-path_bounds(p)[0]+stroke)*zh_scale for p in old_chinese]
phrase_extra = 75.0
zh_gap = (WIDTH-sum(chinese_widths)-phrase_extra)/(len(chars)-1)
assert zh_gap > 20
x = LEFT
for i, (src, char) in enumerate(zip(old_chinese, chars)):
    b = path_bounds(src)
    glyph = copy.deepcopy(src)
    glyph.set('id', f'chinese-{i}')
    glyph.set('data-character', char)
    glyph.set('transform', matrix(zh_scale, x-zh_scale*(b[0]-stroke/2), 720-zh_scale*(cb[1]-stroke/2)))
    chinese.append(glyph)
    x += chinese_widths[i] + (zh_gap if i < len(chars)-1 else 0) + (phrase_extra if i == 4 else 0)
assert abs(x-(LEFT+WIDTH)) < 1e-7
assert ET.tostring(mark) == ET.tostring(parent.find(".//*[@data-go-mark]"))
assert [p.get('d') for p in chinese] == [p.get('d') for p in old_chinese]
assert [p.get('d') for p in word] == [p.get('d') for p in old_letters]
assert plus.get('d') == parent.find(".//*[@data-plus]").get('d')

data = ET.tostring(svg, encoding='utf-8', xml_declaration=True)
for name in ['go-main-lockup.svg', 'go-main-lockup-refined-v4.svg']:
    (ASSETS/name).write_bytes(data)
app_bytes = (PARENT/'app.js').read_bytes()
assert digest(app_bytes) == '127cda38da063fc94d276a24ad1ac9dd5fc4516b1e434e8dfa085210b6aa0a61'
old_url = 'go-main-lockup-aligned-v3.svg?v=20260909-aligned-v3'
new_url = 'go-main-lockup-refined-v4.svg?v=20260909-refined-v4'
app = app_bytes.decode()
assert app.count(old_url) == 1
(OUT/'app.js').write_text(app.replace(old_url, new_url))

asset = ASSETS/'go-main-lockup-refined-v4.svg'
result = subprocess.run(['inkscape', str(asset), '--query-all'], check=True, capture_output=True, text=True)
measured = {}
for line in result.stdout.splitlines():
    fields = line.split(',')
    if len(fields) == 5:
        measured[fields[0]] = [float(v) for v in fields[1:]]
e, c, g, r = [measured[k] for k in ['english-line','chinese-line','go-mark','right-block']]
assert abs(e[0]-c[0]) < .03
assert abs((e[0]+e[2])-(c[0]+c[2])) < .03
assert abs(g[1]-r[1]) < .03
assert abs((g[1]+g[3])-(r[1]+r[3])) < .03
last = measured['chinese-11']
assert VIEW_WIDTH-last[0]-last[2] >= MARGIN_X-.03

render_paths = []
for name, width in [('GO_REFINED_V4.png',1600),('QA_320.png',320),('QA_375.png',375),('QA_430.png',430),('QA_240_LIMIT.png',240)]:
    path = ROOT/name
    subprocess.run(['inkscape',str(asset),'--export-type=png',f'--export-filename={path}',f'--export-width={width}','--export-background=white'],check=True,capture_output=True)
    render_paths.append(path)
with fitz.open(stream=data, filetype='svg') as doc:
    pdf_data = doc.convert_to_pdf()
with fitz.open(stream=pdf_data,filetype='pdf') as doc:
    doc[0].get_pixmap(matrix=fitz.Matrix(1600/doc[0].rect.width,1600/doc[0].rect.width),alpha=False).save(ROOT/'QA_SECOND_RENDERER.png')
render_paths.append(ROOT/'QA_SECOND_RENDERER.png')
checks = {}
for path in render_paths:
    im = Image.open(path).convert('RGB')
    bbox = im.convert('L').point(lambda p: 255 if p < 220 else 0).getbbox()
    assert bbox and bbox[0] > 0 and bbox[1] > 0 and bbox[2] < im.width and bbox[3] < im.height
    checks[path.name] = {'pixels':im.size,'ink_bbox':bbox,'right_blank_pixels':im.width-bbox[2], 'subtitle_nominal_height_px':round(280*im.width/VIEW_WIDTH,2)}

record = {
    'parent_commit':'e250091a782148b45a776d3f2af2fa27e9596539',
    'parent_svg_sha256':digest(original), 'new_svg_sha256':digest(data),
    'unchanged': ['G/O exact outlines and geometry','central red block geometry and color','English glyph outlines','all 12 Chinese glyph outlines, including complete 订'],
    'refined': {'english_letter_height':500,'plus_size':plus_size,'plus_position':'upper right','english_word_space':word_gap,'english_pair_gaps':gaps,'chinese_painted_height':280,'chinese_uniform_scale':zh_scale,'chinese_local_stroke_addition':stroke,'chinese_regular_gap':zh_gap,'chinese_phrase_extra_gap':phrase_extra,'line_gap':160,'previous_line_gap_approx':295.226,'divider_centered_between_blocks':True},
    'measured_page_bounds_xywh':{k:measured[k] for k in ['go-mark','right-block','english-line','chinese-line','chinese-11']},
    'equal_line_left_and_right_edges':True,'equal_block_top_and_bottom_edges':True,'final_character_inside_safe_area':True,
    'renders':checks,
    'minimum_full_lockup_width_guidance_px':320,
    'limitations':['Static SVG geometry and two independent renderers only; not live browser or device acceptance.','At 240px the full Chinese tagline is too small for confident readability; do not treat no clipping as readable.','No business code change beyond the single header asset reference; no historical tests rerun, deployment or release-gate promotion.','10/10 is a design target, not an objective test result.'],
}
(ROOT/'REFINEMENT_VERIFIED.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(record,ensure_ascii=False,indent=2))
