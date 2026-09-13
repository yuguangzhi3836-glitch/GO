"""Transactional local media metadata; JSON is a one-time, preserved import source.

The database and immutable files must live on the same local durable filesystem.
Back up this database with SQLite backup (or while writers are stopped), plus files/.
This is not a distributed object store or a network-filesystem certification.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3


class MediaIndex:
    def __init__(self, directory: Path):
        self.path = directory / "index.sqlite3"
        self.legacy_path = directory / "index.json"
        with self.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS media_meta (id INTEGER PRIMARY KEY CHECK(id=1), schema_version INTEGER NOT NULL, revision INTEGER NOT NULL, legacy_sha256 TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS media_assets (asset_id TEXT PRIMARY KEY, hotel_id TEXT, cache_file TEXT, revision INTEGER NOT NULL, record TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS media_assets_hotel ON media_assets(hotel_id)")
            db.execute("CREATE INDEX IF NOT EXISTS media_assets_file ON media_assets(cache_file)")
            meta = db.execute("SELECT * FROM media_meta WHERE id=1").fetchone()
            if meta is None:
                records, digest = {}, None
                if self.legacy_path.exists():
                    raw = self.legacy_path.read_bytes()
                    try:
                        legacy = json.loads(raw)
                        records = self.validate_snapshot(legacy)
                    except (ValueError, TypeError, UnicodeError) as exc:
                        raise ValueError("MEDIA_LEGACY_INDEX_INVALID") from exc
                    digest = hashlib.sha256(raw).hexdigest()
                db.execute("INSERT INTO media_meta VALUES (1,1,0,?)", (digest,))
                for record in records.values():
                    self.save(db, record, revision=1)
                if records:
                    self.bump(db)
            elif meta["schema_version"] != 1:
                raise ValueError("MEDIA_INDEX_SCHEMA_UNSUPPORTED")

    @contextmanager
    def transaction(self, *, write=True):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except sqlite3.DatabaseError as exc:
            if db is not None:
                db.rollback()
            raise ValueError("MEDIA_INDEX_UNAVAILABLE") from exc
        except BaseException:
            if db is not None:
                db.rollback()
            raise
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def validate_snapshot(data):
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("assets"), dict):
            raise ValueError("MEDIA_INDEX_SNAPSHOT_INVALID")
        for key, record in data["assets"].items():
            if not isinstance(key, str) or not key or not isinstance(record, dict) or record.get("asset_id") != key:
                raise ValueError("MEDIA_INDEX_SNAPSHOT_INVALID")
            name = record.get("cache_file")
            if not isinstance(name, str) or not name or Path(name).name != name or name in {".", ".."} or "\\" in name:
                raise ValueError("MEDIA_CACHE_PATH_INVALID")
            if not isinstance(record.get("rights_history", []), list):
                raise ValueError("MEDIA_INDEX_SNAPSHOT_INVALID")
        return data["assets"]

    @staticmethod
    def load(db, asset_id):
        row = db.execute("SELECT record, revision FROM media_assets WHERE asset_id=?", (asset_id,)).fetchone()
        if row is None:
            raise ValueError("MEDIA_ASSET_NOT_FOUND")
        record = json.loads(row["record"])
        record["revision"] = row["revision"]
        return record

    @staticmethod
    def save(db, record, *, revision):
        record["revision"] = revision
        db.execute("INSERT INTO media_assets VALUES (?,?,?,?,?) ON CONFLICT(asset_id) DO UPDATE SET hotel_id=excluded.hotel_id, cache_file=excluded.cache_file, revision=excluded.revision, record=excluded.record",
                   (record["asset_id"], record.get("hotel_id"), record.get("cache_file"), revision,
                    json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)))

    @staticmethod
    def bump(db):
        db.execute("UPDATE media_meta SET revision=revision+1 WHERE id=1")

    def snapshot(self):
        with self.transaction(write=False) as db:
            revision = db.execute("SELECT revision FROM media_meta WHERE id=1").fetchone()[0]
            assets = {row["asset_id"]: json.loads(row["record"]) for row in db.execute("SELECT asset_id,record FROM media_assets")}
            return {"version": 1, "_revision": revision, "assets": assets}

    def replace_snapshot(self, data):
        """Compatibility/repair helper; a stale whole-index snapshot never overwrites newer work."""
        records = self.validate_snapshot(data)
        with self.transaction() as db:
            current = db.execute("SELECT revision FROM media_meta WHERE id=1").fetchone()[0]
            expected = data.get("_revision", 0)
            if type(expected) is not int or current != expected:
                raise ValueError("MEDIA_INDEX_REVISION_CONFLICT")
            previous = {r["asset_id"]: r["revision"] for r in db.execute("SELECT asset_id,revision FROM media_assets")}
            db.execute("DELETE FROM media_assets")
            for record in records.values():
                self.save(db, record, revision=previous.get(record["asset_id"], 0) + 1)
            self.bump(db)

    def get(self, asset_id):
        with self.transaction(write=False) as db:
            return self.load(db, asset_id)

    def insert(self, record, admit_file):
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM media_assets WHERE asset_id=?", (record["asset_id"],)).fetchone():
                raise ValueError("MEDIA_ASSET_ALREADY_EXISTS")
            admit_file()
            self.save(db, record, revision=1)
            self.bump(db)
        return record

    def update(self, asset_id, change, expected_revision=None):
        with self.transaction() as db:
            record = self.load(db, asset_id)
            if expected_revision is not None and (type(expected_revision) is not int or record["revision"] != expected_revision):
                raise ValueError("MEDIA_ASSET_REVISION_CONFLICT")
            revision = record["revision"]
            change(record)
            self.save(db, record, revision=revision + 1)
            self.bump(db)
        return record

    def purge_hotel(self, hotel_id, delete_file):
        # First commit the removal. A crash can leave an unreferenced file, never a
        # rolled-back row pointing to a deleted file. Then recheck references under
        # the same writer lock used by admission, including other hotel assets.
        with self.transaction() as db:
            rows = db.execute("SELECT cache_file FROM media_assets WHERE hotel_id=?", (hotel_id,)).fetchall()
            db.execute("DELETE FROM media_assets WHERE hotel_id=?", (hotel_id,))
            if rows:
                self.bump(db)
        with self.transaction() as db:
            for name in {r["cache_file"] for r in rows}:
                if name and not db.execute("SELECT 1 FROM media_assets WHERE cache_file=? LIMIT 1", (name,)).fetchone():
                    delete_file(name)
        return {"hotel_id": hotel_id, "removed_count": len(rows)}
