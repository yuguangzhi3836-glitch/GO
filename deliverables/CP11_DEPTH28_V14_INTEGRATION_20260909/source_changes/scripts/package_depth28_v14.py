#!/usr/bin/env python3
"""Seal the V14 three-surface integration as a deterministic DEPTH28 delta."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path


CHANGED = [
    "design/brand/depth28/SUBBRAND_HIERARCHY.json",
    "frontend/admin/index.html",
    "frontend/consumer/app.js",
    "frontend/consumer/direct.html",
    "frontend/consumer/flight-journeys.js",
    "frontend/consumer/index.html",
    "frontend/consumer/vi-reference-10.css",
    "frontend/consumer/assets/go-ai.svg",
    "frontend/consumer/assets/go-offer.svg",
    "frontend/consumer/assets/go-main-lockup.svg",
    "frontend/consumer/assets/go-main-lockup-v14.svg",
    "frontend/consumer/assets/go-compact-lockup-v14.svg",
    "frontend/consumer/assets/go-mark.svg",
    "frontend/consumer/assets/go-symbol.svg",
    "frontend/consumer/assets/go-symbol-on-color.svg",
    "frontend/consumer/assets/go-symbol-v14.svg",
    "frontend/consumer/assets/go-symbol-v14-reverse.svg",
    "frontend/shared/app.js",
    "frontend/shared/styles.css",
    "frontend/shared/go-mark.svg",
    "frontend/shared/go-mark-inverse.svg",
    "frontend/shared/go-compact-v14-reverse.svg",
    "frontend/shared/go-symbol-v14.svg",
    "frontend/shared/go-symbol-v14-reverse.svg",
    "frontend/supplier/index.html",
    "scripts/apply_depth28_v14_vi.py",
    "scripts/package_depth28_v14.py",
    "scripts/preview_network_interfaces.cjs",
    "tests_frontend/brand_v14.test.mjs",
]

PARENT_COMMIT = "9b3e03f62a7e808a979c154e7bb1e7435069df88"
V14_COMMIT = "619f80359fce8ee79c4b8651f1d5be4aa4382e6f"
V14_MASTER_SHA256 = "ad492e6e4bd8c29ff541b155f02e061ae0cb4f2cc971126047e3589c267c513d"


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def tree_digest(fingerprint: dict[str, str]) -> str:
    body = b"".join(path.encode() + b"\0" + fingerprint[path].encode() + b"\n" for path in sorted(fingerprint))
    return digest_bytes(body)


def zip_write(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, (2026, 9, 9, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    zf.writestr(info, data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    parent = args.parent.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("NEW_OUTPUT_DIRECTORY_REQUIRED")

    parent_fingerprint_path = parent / "deliverables/CP11_DEPTH27_20260909/SOURCE_FINGERPRINT.json"
    parent_fingerprint = json.loads(parent_fingerprint_path.read_text())
    for rel, expected in parent_fingerprint.items():
        path = parent / rel
        if not path.is_file() or digest(path) != expected:
            raise SystemExit("PARENT_FINGERPRINT_MISMATCH:" + rel)

    rows = []
    final_fingerprint = dict(parent_fingerprint)
    for rel in CHANGED:
        candidate = root / rel
        if not candidate.is_file():
            raise SystemExit("CANDIDATE_FILE_MISSING:" + rel)
        before = digest(parent / rel) if (parent / rel).is_file() else None
        after = digest(candidate)
        rows.append({"path": rel, "before_sha256": before, "sha256": after, "size": candidate.stat().st_size})
        final_fingerprint[rel] = after

    source_tree_sha = tree_digest(final_fingerprint)
    output.mkdir(parents=True)
    (output / "source_changes").mkdir()
    for rel in CHANGED:
        target = output / "source_changes" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, target)

    manifest = {
        "build": "DEPTH28_V14_THREE_SURFACE_INTEGRATION",
        "parent_commit": PARENT_COMMIT,
        "v14_commit": V14_COMMIT,
        "v14_master_sha256": V14_MASTER_SHA256,
        "source_tree_sha256": source_tree_sha,
        "source_tree_scope": "DEPTH27 fingerprint plus the exact listed DEPTH28 files; runtime, caches and prior deliverables excluded",
        "files": rows,
    }
    dump(output / "SOURCE_MANIFEST.json", manifest)
    dump(output / "PARENT_SOURCE_FINGERPRINT.json", parent_fingerprint)
    dump(output / "SOURCE_FINGERPRINT.json", final_fingerprint)

    evidence_out = output / "evidence"
    shutil.copytree(root / "verification/current_build/depth28", evidence_out)
    browser = {
        "environment": "isolated local preview candidate",
        "preview_server": "STARTED",
        "consumer_supplier_admin_http": "NOT_OBSERVED_FROM_CLOUD_BROWSER",
        "cloud_browser_attempts": [
            {"url": "http://terminal.local:4174/go-app/", "result": "ERR_BLOCKED_BY_CLIENT"},
            {"url": "http://terminal.local:5173/go-app/", "result": "ERR_BLOCKED_BY_CLIENT"},
            {"url": "http://terminal.local/go-app/", "result": "ERR_BLOCKED_BY_CLIENT"},
        ],
        "desktop_post_login": "HOLD",
        "mobile_viewports": "HOLD",
        "hk_runtime": "NOT_TOUCHED",
        "claim_limit": "No browser PASS is claimed from static or HTTP-unit evidence.",
    }
    dump(evidence_out / "BROWSER_ACCEPTANCE.json", browser)

    status = {
        "build": "DEPTH28_V14_THREE_SURFACE_INTEGRATION",
        "implemented": True,
        "locally_tested": True,
        "independently_tested": False,
        "release_approved": False,
        "deployed": False,
        "verified_in_hk": False,
        "tests": {"affected_python": {"passed": 59, "failed": 0}, "frontend_node": {"passed": 135, "failed": 0}},
        "vi": {
            "primary_v14": "LOCKED_UNCHANGED",
            "subbrand_go_tier": "RECESSIVE",
            "subbrand_go_scale_vs_previous": 0.8333333333,
            "subbrand_go_opacity": 0.78,
        },
        "gate_chain": {
            "THREE_END_REAL_UX_LOGIN": "HOLD",
            "SIX_VERTICAL_REAL_CLOSED_LOOP_E2E": "HOLD",
            "SEALED_NODE_GATE": "HOLD",
            "FINAL_RELEASE": "HOLD",
        },
        "earliest_blocker": "Cloud browser could not access the isolated local preview; post-login desktop and mobile journeys remain unobserved.",
        "boundary": "No HK connection, deployment, RDS/Redis/Caddy/schema/worker/order/payment change.",
    }
    dump(evidence_out / "CURRENT_BUILD_STATUS.json", status)

    readme = f"""# GO DEPTH28 — 锁版 V14 三端集成候选

父候选：`{PARENT_COMMIT}`（DEPTH27）。锁版 VI：`{V14_COMMIT}`，主标志 SHA256 `{V14_MASTER_SHA256}`。

消费者端在宽位使用 V14 完整版，窄页头使用 V14 Compact；供应商端和管理端侧栏使用 V14 反白 Compact，登录页使用 V14 GO 标志。旧运行时资产名同步绑定到同一 V14 几何，避免历史页面回退；三端缓存版本统一为 `20260909-depth28`。

主品牌 V14 锁版字节保持不变。GO AI、GO Offer 的 GO 使用同源 V14 几何，但按子品牌第二视觉层级处理：相对原应用字面缩至 83.3%，视觉浓度为 78%；产品后缀保留各自识别色。规则与资产元数据均已固化，防回归测试禁止子品牌 GO 回升为主品牌层级。

本地受影响回归：Python 59 项通过，Node 前端 135 项通过，0 失败。锁版主资产保持原始字节，新增测试校验精确 SHA256、三端引用和旧资产名防回退。

隔离预览服务已启动，但云浏览器访问本地预览入口返回 `ERR_BLOCKED_BY_CLIENT`，因此没有宣称桌面登录后旅程或手机多尺寸通过。未做独立 CI、香港现场、真实订单或真实支付验收。

门禁顺序保持：三端真实 UX/登录 → 六业务真实闭环 E2E → 密封 Node → 最终发布。四级均为 HOLD，未部署香港，未触碰 RDS、Redis、Caddy、锁定 Worker、Schema 或生产边界。
"""
    (output / "README.md").write_text(readme)

    restore_source = (parent / "deliverables/CP11_DEPTH27_20260909/restore_depth27.py").read_text()
    restore_source = restore_source.replace("DEPTH26", "DEPTH27").replace("depth27-restore-", "depth28-restore-")
    (output / "restore_depth28.py").write_text(restore_source)

    delta = output / "GO_CP11_DEPTH28_V14_DELTA_20260909.zip"
    payload = ["SOURCE_MANIFEST.json", "PARENT_SOURCE_FINGERPRINT.json", "SOURCE_FINGERPRINT.json"]
    payload += ["source_changes/" + rel for rel in CHANGED]
    with zipfile.ZipFile(delta, "w") as zf:
        for rel in payload:
            zip_write(zf, rel, (output / rel).read_bytes())

    sums = []
    for path in sorted(p for p in output.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
        sums.append(f"{digest(path)}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    dump(output / "PACKAGE_STATUS.json", {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "build": "DEPTH28_V14_THREE_SURFACE_INTEGRATION",
        "source_tree_sha256": source_tree_sha,
        "delta_sha256": digest(delta),
        "files_changed": len(CHANGED),
        "FINAL_RELEASE_GATE": "HOLD",
    })
    sums = []
    for path in sorted(p for p in output.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
        sums.append(f"{digest(path)}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    print(json.dumps({"output": str(output), "source_tree_sha256": source_tree_sha, "delta_sha256": digest(delta), "changed": len(CHANGED)}, indent=2))


if __name__ == "__main__":
    main()
