"""Reconcile content-addressed media blobs with PostgreSQL durable media metadata.

Filesystem/object storage and PostgreSQL cannot share one transaction. DEPTH10
therefore treats PostgreSQL metadata as authority and makes blob writes immutable
and content-addressed. This reconciler closes the crash window:

- blob exists but no durable metadata -> orphan, quarantine/delete only after grace
- durable metadata exists but blob missing -> mark as blocking evidence; never publish
- blob SHA differs from ledger -> corruption, fail closed

No orphan is auto-published or auto-attributed to a hotel.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import time

from .durable_media_index import durable_media_index_service


@dataclass(frozen=True)
class ReconcileResult:
    referenced: int
    orphaned: int
    quarantined: int
    missing: int
    corrupt: int
    actions: tuple[dict, ...]


class MediaBlobRecoveryService:
    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir or os.getenv("GO_MEDIA_CACHE_DIR", "var/media_cache")).resolve()
        self.files_dir = self.cache_dir / "files"
        self.quarantine_dir = self.cache_dir / "orphan_quarantine"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sha(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def reconcile(self, *, orphan_grace_seconds: int = 3600, quarantine: bool = True) -> ReconcileResult:
        if orphan_grace_seconds < 60:
            raise ValueError("MEDIA_ORPHAN_GRACE_TOO_SHORT")
        assets = durable_media_index_service.list_assets()
        by_file = {str(x.get("cache_file")): x for x in assets if x.get("cache_file")}
        actions = []
        referenced = orphaned = quarantined = missing = corrupt = 0

        for asset in assets:
            name = str(asset.get("cache_file") or "")
            if not name:
                missing += 1
                actions.append({"action": "MISSING_CACHE_FILE_NAME", "asset_id": asset.get("asset_id")})
                continue
            path = (self.files_dir / name).resolve()
            if self.files_dir not in path.parents or not path.exists():
                missing += 1
                actions.append({"action": "MISSING_BLOB", "asset_id": asset.get("asset_id"), "cache_file": name})
                continue
            referenced += 1
            actual = self._sha(path)
            if actual != asset.get("sha256"):
                corrupt += 1
                actions.append({"action": "CORRUPT_BLOB", "asset_id": asset.get("asset_id"), "cache_file": name,
                                "expected_sha256": asset.get("sha256"), "actual_sha256": actual})

        now = time.time()
        for path in self.files_dir.iterdir():
            if not path.is_file() or path.name in by_file:
                continue
            orphaned += 1
            age = max(0, int(now - path.stat().st_mtime))
            action = {"action": "ORPHAN_BLOB", "cache_file": path.name, "age_seconds": age}
            if age >= orphan_grace_seconds and quarantine:
                target = self.quarantine_dir / path.name
                if target.exists():
                    target = self.quarantine_dir / f"{int(now)}-{path.name}"
                shutil.move(str(path), str(target))
                quarantined += 1
                action.update({"action": "QUARANTINED_ORPHAN_BLOB", "quarantine_file": target.name})
            actions.append(action)

        return ReconcileResult(
            referenced=referenced, orphaned=orphaned, quarantined=quarantined,
            missing=missing, corrupt=corrupt, actions=tuple(actions),
        )

    def release_safe(self, result: ReconcileResult) -> bool:
        return result.missing == 0 and result.corrupt == 0


media_blob_recovery_service = MediaBlobRecoveryService()
