from __future__ import annotations
from pathlib import Path
from zipfile import ZipFile
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

# Product-language debt: active product/runtime docs and source may not use the retired hotel claim terminology.
for base in (ROOT/'src', ROOT/'docs'):
    for p in base.rglob('*'):
        if not p.is_file() or 'archive' in p.parts or p.suffix.lower() not in {'.py','.md','.txt','.json','.tsx','.ts','.js'}:
            continue
        text = p.read_text(encoding='utf-8', errors='ignore')
        if re.search(r'\bhotel\s+claim\b|HOTEL_CLAIM', text, re.I):
            raise SystemExit(f'ACTIVE_HOTEL_CLAIM_TERMINOLOGY:{p.relative_to(ROOT)}')

# Commercial debt: active runtime must not contain the retired implicit 59900 minor-unit subscription default.
for p in (ROOT/'src').rglob('*.py'):
    text = p.read_text(encoding='utf-8', errors='ignore')
    if '59900' in text:
        raise SystemExit(f'LEGACY_599_SUBSCRIPTION_DEFAULT:{p.relative_to(ROOT)}')

# Version-governance debt: bundled V6.1 master may reference V5.4 historically, but may not assert it as current authority.
docx = ROOT/'GO_ULTIMATE_MASTER_PLAN_V6.1_2026-08-22_THREE_TIER_POSITIONING_MASTER.docx'
with ZipFile(docx) as z:
    xml = z.read('word/document.xml')
root = ET.fromstring(xml)
ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
paras=[]
for p in root.findall('.//w:p', ns):
    parts=[t.text or '' for t in p.findall('.//w:t',ns)]
    if parts: paras.append(''.join(parts))
text='\n'.join(paras)
for banned in (
    '以 V5.4 为准',
    'V5.4 为唯一最高控制基线',
    'V5.4 为当前控制版本',
    'V5.4 继续作为最高控制基线',
):
    if banned in text:
        raise SystemExit('STALE_V5_4_CURRENT_CONTROL_ASSERTION:'+banned)
if 'V6.1 是唯一最高控制版本' not in text and 'V6.1 为唯一最高控制基线' not in text:
    raise SystemExit('V6_1_SOLE_CONTROL_ASSERTION_MISSING')

print('R8.1_CONTROL_DEBT_GATE: PASS')
