"""Refine the preserved outlined V7 GO artwork and produce static V8 proofs.

Run with Python 3, fontTools, Pillow, PyMuPDF and Inkscape. No source fonts,
network, browser, application runtime or deployment are needed.
"""
from pathlib import Path
from datetime import datetime, timezone
import copy
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from fontTools.pens.boundsPen import BoundsPen
from fontTools.svgLib.path import parse_path
from PIL import Image
import fitz

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'assets'
ASSETS.mkdir(exist_ok=True)
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
tag = lambda x: '{' + NS + '}' + x
sha = lambda x: hashlib.sha256(x).hexdigest()
source = ROOT / 'inputs/GO_LIGHTER_V7.svg'
if not source.exists():
    source.parent.mkdir(exist_ok=True)
    source.write_bytes((ROOT.parent / 'go-brand-light-v7-20260909/GO_LIGHTER_V7.svg').read_bytes())
assert sha(source.read_bytes()) == 'f08ddbe68f7a48f3121f601fee90be0ca9da8b6b3f33128b8016cbcf5a6d75d9'
base = ET.fromstring(source.read_bytes())

def get(root, name):
    return root.find(f".//*[@id='{name}']")

def bounds(p):
    pen = BoundsPen(None)
    parse_path(p.get('d'), pen)
    return pen.bounds

def matrix(p, s, x, y):
    p.set('transform', f'matrix({s:.12f} 0 0 {s:.12f} {x:.12f} {y:.12f})')

def save(root, path):
    path.write_bytes(ET.tostring(root, encoding='utf-8', xml_declaration=True))
    return path

def arrange_english(root, left, top, height, word_width, word_gap, plus_size, plus_gap):
    letters = list(get(root, 'wordmark'))
    bs = [bounds(p) for p in letters]
    sw = float(get(root, 'wordmark').get('stroke-width'))
    y0 = min(b[1] for b in bs) - sw/2
    y1 = max(b[3] for b in bs) + sw/2
    s = height / (y1-y0)
    widths = [(b[2]-b[0]+sw)*s for b in bs]
    # Optical pair spacing: A/I, D/I, I/R, R/E, E/C, C/T.
    weights = [1.02, .96, .91, .93, .95, .86]
    unit = (word_width-sum(widths)-word_gap)/sum(weights)
    gaps = [weights[0]*unit, word_gap, *[w*unit for w in weights[1:]]]
    assert min(gaps) > 0
    x = left
    for i,(p,b,w) in enumerate(zip(letters,bs,widths)):
        matrix(p,s,x-s*(b[0]-sw/2),top-s*y0)
        x += w + (gaps[i] if i < 7 else 0)
    assert abs(x-left-word_width)<1e-6
    p = get(root, 'plus')
    b = bounds(p)
    sp = plus_size/(b[2]-b[0])
    t_top = top + s*(bs[7][1]-sw/2-y0)
    matrix(p,sp,x+plus_gap-sp*b[0],t_top-sp*b[1])
    return {'height':height,'letter_pair_gaps':gaps,'word_gap':word_gap,
            'plus_size':plus_size,'plus_gap':plus_gap}

def master(divider=False):
    r = copy.deepcopy(base)
    r.set('id','go-master-v8')
    r.set('viewBox','-240 -120 6530 1240')
    r.find(tag('title')).text = 'GO AI DIRECT+ / 发现全世界 直接向官方预订'
    mark = get(r,'go-mark')
    mark.set('data-go-mark','equal-circles-v8-optical-crossbar')
    list(mark)[1].set('id','g-crossbar')
    list(mark)[1].set('d','M602 432 H1030 V568 H466 Z')
    list(mark)[0].set('id','g-ring')
    list(mark)[2].set('id','o-ring')
    list(mark)[3].set('id','red-connector')
    # Preserve outer circles, inner rings, and the connector exactly as V7.
    for idx in [0,2,3]:
        for key,value in list(get(base,'go-mark'))[idx].attrib.items():
            assert list(mark)[idx].get(key)==value
    line = get(r,'divider')
    if divider:
        line.set('x1','2230'); line.set('x2','2230')
        line.set('stroke-opacity','.19'); line.set('stroke-width','9')
    else:
        r.remove(line)
    get(r,'right-block').set('data-right-block','v8-outlined')
    e = arrange_english(r,2410,0,520,3370,246,200,70)
    cn = get(r,'chinese-line')
    cn.set('data-subtitle','v8-optical-tracking')
    sw = float(cn.get('stroke-width'))
    bs = [bounds(p) for p in cn]
    y0 = min(b[1] for b in bs)-sw/2
    y1 = max(b[3] for b in bs)+sw/2
    height = 258.0
    s = height/(y1-y0)
    widths = [(b[2]-b[0]+sw)*s for b in bs]
    phrase_extra_gap = 74.0
    gap = (3640-sum(widths)-phrase_extra_gap)/11
    x = 2410.0
    for i,(p,b,w) in enumerate(zip(cn,bs,widths)):
        matrix(p,s,x-s*(b[0]-sw/2),1000-height-s*y0)
        assert p.get('d')==list(get(base,'chinese-line'))[i].get('d')
        x += w + (gap if i<11 else 0) + (phrase_extra_gap if i==4 else 0)
    assert abs(x-6050)<1e-6
    assert ''.join(p.get('data-character') for p in cn)=='发现全世界直接向官方预订'
    return r, {'english':e,'chinese':{'height':height,'visible_gap':gap,'phrase_extra_gap':phrase_extra_gap}}

main, layout = master()
main_path = save(main,ASSETS/'go-master-v8.svg')

compact = copy.deepcopy(main)
compact.set('id','go-compact-v8')
compact.set('aria-label','GO AI DIRECT+')
compact.find(tag('title')).text = 'GO AI DIRECT+ / compact lockup'
get(compact,'right-block').remove(get(compact,'chinese-line'))
arrange_english(compact,2410,175,650,3990,250,240,94)
compact.set('viewBox','-200 -120 7134 1240')
compact_path = save(compact,ASSETS/'go-compact-v8.svg')

mark = ET.Element(tag('svg'), {'id':'go-mark-v8','viewBox':'-175 -175 2400 1350',
    'preserveAspectRatio':'xMidYMid meet','role':'img','aria-label':'GO'})
ET.SubElement(mark,tag('title')).text='GO / mark'
mark.append(copy.deepcopy(get(main,'go-mark')))
mark_path = save(mark,ASSETS/'go-mark-v8.svg')

def filled_outlines(path):
    """Bake strokes once so SVG consumers do not reinterpret stroke transforms."""
    old=ET.fromstring(path.read_bytes())
    tmp=path.with_name(path.stem+'-outline-tmp.svg')
    subprocess.run(['inkscape',str(path),'--export-type=svg','--export-plain-svg',
        f'--export-filename={tmp}','--actions=select-all:all;object-stroke-to-path;export-do'],
        check=True,capture_output=True)
    r=ET.fromstring(tmp.read_bytes())
    # Inkscape retains inherited strokes on groups after creating filled stroke
    # outlines. Remove inheritance to avoid drawing a second outline.
    for e in r.iter():
        if 'style' in e.attrib:
            style=dict(kv.split(':',1) for kv in e.get('style').split(';') if ':' in kv)
            for key in ['fill','fill-rule','clip-rule','opacity','fill-opacity']:
                if key in style:e.set(key,style[key])
            del e.attrib['style']
        for key in list(e.attrib):
            if key.startswith('stroke'):del e.attrib[key]
        if e.get('id'):
            orig=get(old,e.get('id'))
            if orig is not None:
                for key,value in orig.attrib.items():
                    if key.startswith('data-'): e.set(key,value)
    save(r,path);tmp.unlink()
    assert not any(e.get('stroke') for e in r.iter())
    return r

main=filled_outlines(main_path)
compact=filled_outlines(compact_path)

def palette(svg,ink,accent):
    r = copy.deepcopy(svg)
    for e in r.iter():
        for a in ['fill','stroke']:
            if e.get(a,'').lower()=='#061b3a': e.set(a,ink)
            elif e.get(a,'').lower()=='#ff3b24': e.set(a,accent)
    return r

reverse=palette(main,'#FFFFFF','#FF3B24')
mono=palette(main,'#111111','#111111')
save(reverse,ASSETS/'go-master-v8-reverse.svg')
save(mono,ASSETS/'go-master-v8-mono.svg')
save(palette(compact,'#FFFFFF','#FF3B24'),ASSETS/'go-compact-v8-reverse.svg')
save(palette(mark,'#FFFFFF','#FF3B24'),ASSETS/'go-mark-v8-reverse.svg')

def query(path):
    r=subprocess.run(['inkscape',str(path),'--query-all'],check=True,capture_output=True,text=True)
    return {v[0]:[float(n) for n in v[1:]] for v in [line.split(',') for line in r.stdout.splitlines()] if len(v)==5}

def near(a,b):
    assert abs(a-b)<.03,(a,b)

mb=query(main_path)
cb=query(compact_path)
for b in [mb,cb]: near(b['plus'][1],b['english-7'][1])
for i in [0,2]: near(mb['english-line'][i],mb['chinese-line'][i])
for i in [1,3]: near(mb['go-mark'][i],mb['right-block'][i])
near(mb['g-ring'][1],mb['o-ring'][1]); near(mb['g-ring'][3],mb['o-ring'][3])
assert mb['plus'][2:]==[200,200]
assert not list(main.iter(tag('text')))
assert mb['chinese-11'][0]+mb['chinese-11'][2] < 6530-230

render_checks=[]
def render(path,width,filename,bg='white',engine='inkscape'):
    dest=ROOT/filename
    if engine=='inkscape':
        subprocess.run(['inkscape',str(path),'--export-type=png',f'--export-filename={dest}',
            f'--export-width={width}',f'--export-background={bg}','--export-background-opacity=1'],
            check=True,capture_output=True)
    else:
        with fitz.open(stream=path.read_bytes(),filetype='svg') as d: pdf=d.convert_to_pdf()
        with fitz.open(stream=pdf,filetype='pdf') as d:
            s=width/d[0].rect.width
            d[0].get_pixmap(matrix=fitz.Matrix(s,s),alpha=False).save(dest)
    im=Image.open(dest).convert('RGB')
    if bg=='white':
        box=im.convert('L').point(lambda v:255 if v<220 else 0).getbbox()
        assert box and 0<box[0]<box[2]<im.width and 0<box[1]<box[3]<im.height,(filename,box)
    else: box=None
    render_checks.append({'file':filename,'width_px':im.width,'height_px':im.height,
        'engine':engine,'ink_bounds':box,'background':bg})
    return dest

render(main_path,1800,'GO_MASTER_V8.png')
render(main_path,400,'GO_MASTER_V8_400.png')
render(main_path,320,'GO_MASTER_V8_320.png')
render(compact_path,200,'GO_COMPACT_V8_200.png')
render(compact_path,160,'GO_COMPACT_V8_160.png')
render(mark_path,48,'GO_MARK_V8_48.png')
render(mark_path,32,'GO_MARK_V8_32.png')
render(ASSETS/'go-master-v8-reverse.svg',1800,'GO_REVERSE_V8.png',bg='#061B3A')
render(main_path,1800,'GO_MASTER_V8_SECOND_RENDERER.png',engine='mupdf')
render(main_path,400,'GO_MASTER_V8_400_SECOND_RENDERER.png',engine='mupdf')
render(compact_path,160,'GO_COMPACT_V8_160_SECOND_RENDERER.png',engine='mupdf')

# A flat vector specimen, with source artwork embedded at declared sizes.
# This is an application design proof, not a screenshot of a running product.
sheet=ET.Element(tag('svg'),{'viewBox':'0 0 1440 1070','width':'1440','height':'1070'})
ET.SubElement(sheet,tag('rect'),{'width':'1440','height':'1070','fill':'#F6F7F9'})
ET.SubElement(sheet,tag('rect'),{'x':'40','y':'40','width':'1360','height':'360','fill':'white'})
ET.SubElement(sheet,tag('rect'),{'x':'40','y':'422','width':'1360','height':'300','fill':'#061B3A'})
ET.SubElement(sheet,tag('rect'),{'x':'40','y':'744','width':'664','height':'286','fill':'white'})
ET.SubElement(sheet,tag('rect'),{'x':'724','y':'744','width':'676','height':'286','fill':'white'})

def label(x,y,text,size=13,fill='#69778C'):
    e=ET.SubElement(sheet,tag('text'),{'x':str(x),'y':str(y),'font-family':'DejaVu Sans',
        'font-size':str(size),'letter-spacing':'1.3','fill':fill})
    e.text=text

def place(svg,x,y,w):
    s=copy.deepcopy(svg)
    vb=[float(n) for n in s.get('viewBox').split()]
    s.set('x',str(x));s.set('y',str(y));s.set('width',str(w));s.set('height',str(w*vb[3]/vb[2]))
    # Every inline specimen must have distinct IDs, for standalone rendering.
    for e in s.iter():
        if 'id' in e.attrib: e.set('id',f'{x}-{y}-'+e.get('id'))
    sheet.append(s)

label(76,83,'GO / VISUAL IDENTITY',14,'#061B3A')
label(1206,83,'MASTER 08',12)
place(main,104,136,1232)
label(76,465,'REVERSE / DEEP NAVY',12,'#AEBBD0')
place(reverse,104,475,1232)
label(76,788,'COMPACT / 200 PX + 160 PX')
place(compact,76,835,200)
place(compact,76,911,160)
place(mark,388,844,48)
place(mark,503,850,32)
label(390,953,'48 PX',10);label(505,953,'32 PX',10)
label(760,788,'BILINGUAL / 400 PX')
place(main,760,815,400)
label(760,925,'MONO / OUTLINED VECTOR',10)
place(mono,760,944,340)
board=save(sheet,ROOT/'GO_APPLICATIONS_V8.svg')
render(board,1440,'GO_APPLICATIONS_V8.png')

# Deliver a transparent master as well as white-background previews.
subprocess.run(['inkscape',str(main_path),'--export-type=png',
    f'--export-filename={ROOT/"GO_MASTER_V8_TRANSPARENT.png"}',
    '--export-width=2400','--export-background-opacity=0'],check=True,capture_output=True)
transparent=Image.open(ROOT/'GO_MASTER_V8_TRANSPARENT.png')
assert transparent.mode=='RGBA' and transparent.getchannel('A').getextrema()==(0,255)

# Review the divider at identical geometry; only the selected no-divider master
# belongs to the final assets. Alternatives are scratch inspection output.
review=ROOT.parent/'go-v8-review'
review.mkdir(exist_ok=True)
alt,_=master(True)
save(alt,review/'with-divider.svg')
subprocess.run(['inkscape',str(review/'with-divider.svg'),'--export-type=png',
    f'--export-filename={review/"with-divider.png"}','--export-width=1800','--export-background=white'],
    check=True,capture_output=True)

record={'created_at_utc':datetime.now(timezone.utc).isoformat(),
    'parent_commit':'c28ae4ff7514a0ec1417402920d85e46d65bb9fa',
    'parent_svg_sha256':sha(source.read_bytes()),'master_svg_sha256':sha(main_path.read_bytes()),
    'layout':layout,'changes':{'G_crossbar_height':{'before':150,'after':136},
        'G_O_ring_width':165,'left_right_gap':{'before':420,'after':360},
        'Chinese_height':{'before':280,'after':258},'divider':'removed'},
    'measured_bounds_xywh':{k:mb[k] for k in ['g-ring','g-crossbar','o-ring','red-connector',
        'go-mark','right-block','english-line','chinese-line','plus','english-7','chinese-11']},
    'constraints':{'G_O_equal_diameter':True,'red_connector_geometry_and_color_preserved':True,
        'left_right_equal_visible_height':True,'english_plus_chinese_equal_visible_edges':True,
        'plus_top_aligned_with_T':True,'all_Chinese_outlines_preserved':True,
        'runtime_font_independent':True,'lettering_strokes_baked_to_filled_outlines':True},
    'render_checks':render_checks,
    'proposed_usage':{'bilingual_master_min_width_px':400,'compact_min_width_px':160,
        'mark_min_width_px':32,'bilingual_print_min_width_mm':60},
    'scope':'Static vector geometry and raster proof. No browser, physical mobile, physical print or Hong Kong release verification.',
    'aesthetic_score':'Not a machine-verifiable measure. No automated perfect-score claim.'}
(ROOT/'DESIGN_VERIFIED.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'layout':layout,'constraints':record['constraints'],'render_count':len(render_checks)},ensure_ascii=False,indent=2))
