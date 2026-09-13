#!/usr/bin/env python3
"""Apply the locked GO V14 VI to a restored candidate without altering prior evidence."""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


EXPECTED = {
    "GO_MASTER_V14.svg": "ad492e6e4bd8c29ff541b155f02e061ae0cb4f2cc971126047e3589c267c513d",
    "GO_COMPACT_V14.svg": "2d1fad1032acadcb9ff03e19c35c6dc249586942381546893292220156bd114b",
    "GO_COMPACT_V14_REVERSE.svg": "5bea6572eb39e96e34384d0076dd81662a8e9d23f549dfc7ecb1bfd24f2aac99",
    "GO_SYMBOL_V14.svg": "5066c0796c25a5ef7200bed22368660fb2f567e2f2bfd491f125cda66f7d2c2e",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_read(root: Path, name: str) -> bytes:
    data = (root / name).read_bytes()
    actual = sha256(data)
    if actual != EXPECTED[name]:
        raise SystemExit(f"LOCKED_V14_HASH_MISMATCH {name} expected={EXPECTED[name]} actual={actual}")
    return data


def write_exact(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if path.read_bytes() != data:
        raise SystemExit(f"WRITE_VERIFY_FAILED {path}")


def replace_exact(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"EXPECTED_SOURCE_NOT_FOUND {path}: {old[:80]}")
    path.write_text(text.replace(old, new))


def v14_mark(fill: str) -> str:
    return (
        f'<g data-go-mark="equal-circles-lighter-v7" fill="{fill}">'
        '<path data-letter="G" d="M914.519 220.404 A500 500 0 1 0 1000 500 L835 500 A335 335 0 1 1 777.727730 312.670680 Z"/>'
        '<path d="M602 432 H1030 V568 H466 Z"/>'
        '<path data-letter="O" d="M1060.102051 400 A500 500 0 1 1 1060.102051 600 L1230.273554425 600 A335 335 0 1 0 1230.273554425 400 Z"/>'
        '<rect data-connector="red-block" x="1050" y="420" width="160" height="160" fill="#FF3B24"/>'
        '</g>'
    )


def update_subbrand(path: Path) -> None:
    text = path.read_text()
    if 'data-go-mark="equal-circles-v26"' in text:
        text, count = re.subn(r'<g data-go-mark="equal-circles-v26".*?</g>', v14_mark("#061B3A"), text, count=1)
        if count != 1:
            raise SystemExit(f"SUBBRAND_MARK_NOT_FOUND {path}")
    if 'data-subbrand-go="recessive"' in text:
        path.write_text(text)
        return
    if path.name == "go-ai.svg":
        text = text.replace('viewBox="0 0 860 260" role="img" aria-label="GO AI"', 'viewBox="0 0 720 260" role="img" aria-label="GO AI" data-brand-tier="subbrand"')
    elif path.name == "go-offer.svg":
        text = text.replace('viewBox="0 0 1120 260" role="img" aria-label="GO Offer"', 'viewBox="0 0 820 260" role="img" aria-label="GO Offer" data-brand-tier="subbrand"')
    else:
        raise SystemExit(f"UNKNOWN_SUBBRAND {path}")
    text = text.replace('<g transform="translate(0 10) scale(.24)">', '<g data-subbrand-go="recessive" opacity=".78" transform="translate(18 30) scale(.20)">', 1)
    text = text.replace('<text x="540"', '<text x="484"', 1)
    if 'data-subbrand-go="recessive"' not in text:
        raise SystemExit(f"SUBBRAND_HIERARCHY_NOT_APPLIED {path}")
    path.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand-dir", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    brand = args.brand_dir.resolve()

    master = checked_read(brand, "GO_MASTER_V14.svg")
    compact = checked_read(brand, "GO_COMPACT_V14.svg")
    compact_reverse = checked_read(brand, "GO_COMPACT_V14_REVERSE.svg")
    symbol = checked_read(brand, "GO_SYMBOL_V14.svg")
    symbol_reverse = symbol.replace(b'fill="#061B3A"', b'fill="#FFFFFF"')

    outputs = {
        root / "frontend/consumer/assets/go-main-lockup-v14.svg": master,
        root / "frontend/consumer/assets/go-compact-lockup-v14.svg": compact,
        root / "frontend/consumer/assets/go-symbol-v14.svg": symbol,
        root / "frontend/consumer/assets/go-symbol-v14-reverse.svg": symbol_reverse,
        root / "frontend/consumer/assets/go-main-lockup.svg": master,
        root / "frontend/consumer/assets/go-mark.svg": symbol,
        root / "frontend/consumer/assets/go-symbol.svg": symbol,
        root / "frontend/consumer/assets/go-symbol-on-color.svg": symbol_reverse,
        root / "frontend/shared/go-compact-v14-reverse.svg": compact_reverse,
        root / "frontend/shared/go-symbol-v14.svg": symbol,
        root / "frontend/shared/go-symbol-v14-reverse.svg": symbol_reverse,
        root / "frontend/shared/go-mark.svg": symbol,
        root / "frontend/shared/go-mark-inverse.svg": symbol_reverse,
    }
    for path, data in outputs.items():
        write_exact(path, data)
    for name in ("go-ai.svg", "go-offer.svg"):
        update_subbrand(root / "frontend/consumer/assets" / name)

    replace_exact(root / "frontend/consumer/app.js",
        '<img class="go-main-lockup" src="/go-app/assets/go-main-lockup.svg?v=20260909-depth27" alt="GO AI DIRECT+ 发现全世界 直接向官方预订">',
        '<picture class="go-v14-lockup"><source media="(max-width:479px)" srcset="/go-app/assets/go-compact-lockup-v14.svg?v=20260909-depth28"><img class="go-main-lockup" src="/go-app/assets/go-main-lockup-v14.svg?v=20260909-depth28" alt="GO AI DIRECT+ 发现全世界 直接向官方预订"></picture>')
    replace_exact(root / "frontend/consumer/direct.html", '/go-app/assets/go-main-lockup.svg', '/go-app/assets/go-compact-lockup-v14.svg?v=20260909-depth28')
    replace_exact(root / "frontend/consumer/flight-journeys.js", '/go-app/assets/go-main-lockup.svg', '/go-app/assets/go-compact-lockup-v14.svg?v=20260909-depth28')
    replace_exact(root / "frontend/shared/app.js", '/console-assets/go-mark.svg?v=20260909-depth26', '/console-assets/go-symbol-v14.svg?v=20260909-depth28')
    replace_exact(root / "frontend/shared/app.js", '/console-assets/go-mark-inverse.svg?v=20260909-depth26', '/console-assets/go-compact-v14-reverse.svg?v=20260909-depth28')
    replace_exact(root / "frontend/consumer/vi-reference-10.css",
        '.go-main-lockup{display:block;width:257px;height:61px;max-width:calc(100% - 86px);object-fit:contain;object-position:left center;flex:0 1 auto;padding:0!important;border:0!important;transform:none!important}',
        '.go-v14-lockup{display:block;width:257px;max-width:calc(100% - 86px);flex:0 1 auto}.go-main-lockup{display:block;width:100%;height:61px;object-fit:contain;object-position:left center;padding:0!important;border:0!important;transform:none!important}')
    replace_exact(root / "frontend/consumer/vi-reference-10.css", '.go-main-lockup{width:247px;height:58.7px}', '.go-v14-lockup{width:247px}.go-main-lockup{height:58.7px}')
    replace_exact(root / "frontend/consumer/vi-reference-10.css", '.go-main-lockup{width:270px;height:64.3px}', '.go-v14-lockup{width:270px}.go-main-lockup{height:64.3px}')
    replace_exact(root / "frontend/shared/styles.css",
        '.go-brand-lockup img{display:block;width:98px;height:48px;object-fit:contain}',
        '.go-brand-lockup img{display:block;width:190px;height:48px;object-fit:contain;object-position:left center}')
    for path in (root / "frontend/consumer/index.html", root / "frontend/admin/index.html", root / "frontend/supplier/index.html"):
        text = path.read_text().replace('20260909-depth26', '20260909-depth28').replace('20260909-depth27', '20260909-depth28')
        path.write_text(text)

    for path in outputs:
        print(f"V14_ASSET {path.relative_to(root)} {sha256(path.read_bytes())}")
    print("GO_V14_VI_APPLY=PASS")


if __name__ == "__main__":
    main()
