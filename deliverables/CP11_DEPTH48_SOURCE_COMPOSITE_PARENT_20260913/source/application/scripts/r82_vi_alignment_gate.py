#!/usr/bin/env python3
"""R8.2 Consumer VI alignment gate — Design System 1.0 frozen baseline.

R1.4.1 retains the frozen Consumer design baseline while validating the
five-vertical DOM, cache marker, scoped visual layer, and corrected lockup.
Supplier/Admin checks remain non-invasive.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
consumer = (ROOT/'frontend/consumer/app.js').read_text(encoding='utf-8')
css = (ROOT/'frontend/consumer/styles.css').read_text(encoding='utf-8')
index = (ROOT/'frontend/consumer/index.html').read_text(encoding='utf-8')
vertical_css = (ROOT/'frontend/consumer/vertical-frozen-r1.4.css').read_text(encoding='utf-8')
assets = ROOT/'frontend/consumer/assets'
shared = (ROOT/'frontend/shared/styles.css').read_text(encoding='utf-8')
supplier = (ROOT/'frontend/supplier/config.js').read_text(encoding='utf-8')
admin = (ROOT/'frontend/admin/config.js').read_text(encoding='utf-8')


def check(name, ok):
    print(f'{name}={"PASS" if ok else "FAIL"}')
    return ok

required_assets = [
    'go-symbol.svg','go-main-lockup.svg','go-ai.svg','go-offer.svg','go-symbol-on-color.svg',
    'icons/hotel.svg','icons/flight.svg','icons/rail.svg','icons/rental.svg','icons/attraction.svg',
    'icons/home.svg','icons/trips.svg','icons/favorite.svg','icons/messages.svg','icons/profile.svg',
    'icons/bell.svg','icons/mic.svg',
]
asset_ok = all((assets/p).is_file() for p in required_assets)
asset_text = '\n'.join((assets/p).read_text(encoding='utf-8') for p in required_assets if (assets/p).is_file())
no_raster = not re.search(r'<image\b|base64|filter=', asset_text, re.I)
all_viewbox = all('viewBox=' in (assets/p).read_text(encoding='utf-8') for p in required_assets if (assets/p).is_file())

api_paths = set(re.findall(r"['\"](/v1/[^'\"`? ]+)", consumer))


def between(text,start,end):
    a=text.find(start); b=text.find(end,a+1) if a>=0 else -1
    return text[a:b if b>=0 else None] if a>=0 else ''
nav_snip=between(consumer,'function consumerNav','function shell')
home_snip=between(consumer,'function showHome','function showHotelSearch')

items = {
    'consumer_frozen_navy_present': '#071B55'.lower() in css.lower(),
    'consumer_frozen_blue_present': '#0878F9'.lower() in css.lower(),
    'consumer_frozen_orange_present': '#FF4B16'.lower() in css.lower(),
    'consumer_cache_marker_r1_4_1': 'consumer=20260827-r1.4.1' in index,
    'consumer_vertical_layer_linked': 'vertical-frozen-r1.4.css?consumer=20260827-r1.4.1' in index,
    'consumer_vertical_layer_scoped': 'body.go-vertical-mode' in vertical_css,
    'consumer_header_r1_4_1_lockup_geometry': '.go-main-lockup{width:236px' in css and 'viewBox="0 0 236 56"' in (assets/'go-main-lockup.svg').read_text(encoding='utf-8'),
    'consumer_vertical_cta_no_blue_area_fill': '.btn.primary{background:#fff' in css,
    'consumer_r11_info_strips_hidden': '.go-info-strip{display:none!important}' in css,
    'consumer_source_truth_matrix_present': (ROOT/'VI_SOURCE_OF_TRUTH_MATRIX_R1_2.json').is_file() and (ROOT/'FIVE_VERTICAL_VI_SOURCE_OF_TRUTH_MATRIX_R1_4_20260827.md').is_file(),
    'consumer_svg_asset_set_complete': asset_ok,
    'consumer_svg_all_have_viewbox': all_viewbox,
    'consumer_svg_no_raster_base64_filter': no_raster,
    'consumer_main_logo_is_svg_asset': '/go-app/assets/go-main-lockup.svg' in consumer,
    'consumer_subbrands_are_svg_assets': '/go-app/assets/go-ai.svg' in consumer and '/go-app/assets/go-offer.svg' in consumer,
    'consumer_category_icons_svg': all(f'/go-app/assets/icons/{x}.svg' in consumer for x in ['hotel','flight','rail','rental','attraction']),
    'consumer_bottom_nav_exact_five': all(label in consumer for label in ['首页','行程','收藏','消息','我的']) and "['search'" not in nav_snip,
    'consumer_home_dual_column': 'grid-template-columns:repeat(2,minmax(0,1fr))' in css and 'frozen-dual-entry' in home_snip,
    'consumer_home_exact_five_verticals': all(v in home_snip for v in ['data-home-vertical="HOTEL"','data-home-vertical="FLIGHT"','data-home-vertical="RAIL"','data-home-vertical="MOBILITY"','data-home-vertical="ATTRACTION"']) and 'data-home-vertical="RIDE"' not in home_snip and 'showHomeMobilityChooser' in home_snip,
    'consumer_vertical_mode_lifecycle': all(x in consumer for x in ['function setVerticalVIMode(on)', 'function showHome(focus=false){setVerticalVIMode(false)', 'function showHotelSearch(){setVerticalVIMode(true)', 'function showFlightSearch(){setVerticalVIMode(true)', 'function showRailSearch(){setVerticalVIMode(true)', 'function showMobilitySearch(kind){setVerticalVIMode(true)', 'function showAttractionSearch(){setVerticalVIMode(true)']),
    'consumer_rating_unique_format': 'GO <span>★★★★★</span><sup>+</sup> <i>·</i> 4.9' in consumer and 'GO 4.9' not in home_snip,
    'consumer_trust_layer_exact_copy': all(x in consumer for x in ['直连官方','交易更直接','独立判断','只推荐值得的','官方专享','尊享更多礼遇']),
    'consumer_no_character_nav_icons': not any(x in nav_snip for x in ['⌂','▣','♡','◌','♙']),
    'consumer_api_path_count_unchanged_contract': len(api_paths) == 24,
    'supplier_go_name_unchanged': "title:'GO 合作伙伴平台'" in supplier,
    'admin_go_name_unchanged': "title:'GO 运营管理系统'" in admin,
    'mobile_supplier_admin_nav_gate_preserved': '.supplier-mobile-bottom{display:grid;grid-template-columns:repeat(5,1fr)' in shared and '.admin-mobile-bottom{display:grid;grid-template-columns:repeat(5,1fr)' in shared,
}

failed=[k for k,v in items.items() if not check(k,v)]
if failed:
    print('R8.2_VI_ALIGNMENT_GATE: BLOCK '+','.join(failed))
    raise SystemExit(1)
print('R8.2_VI_ALIGNMENT_GATE: PASS / GO Consumer Design System 1.0')
