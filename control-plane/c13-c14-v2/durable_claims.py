"""Persistent C14 replay protection for a trusted local host state directory.

Provision once during controlled installation; normal execution opens an
existing store only. Never delete, restore an older copy, or automatically
recreate the store on errors. A consumed claim stays consumed after failures.
The directory must be on a local filesystem with SQLite/fsync guarantees.
"""
from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import re
import sqlite3
import stat

from acceptance_gate import Refusal


def _identity(value: str) -> None:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", value):
        raise Refusal("claim_identity")


def _private_file(path: Path, directory: bool = False) -> None:
    info = path.lstat()
    correct_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not correct_type or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise Refusal("claim_store_permissions")


class DurableClaims:
    def __init__(self, path: Path, runner_id: str):
        if type(runner_id) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}", runner_id):
            raise Refusal("claim_identity")
        self.path, self.runner_id = Path(path), runner_id
        if not self.path.is_absolute():
            raise Refusal("claim_store_path")

    def _connect(self):
        _private_file(self.path.parent, directory=True)
        _private_file(self.path)
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=5)
        try:
            db.execute("PRAGMA synchronous=FULL")
            if db.execute("SELECT version, runner_id FROM identity").fetchall() != [(1, self.runner_id)]:
                raise Refusal("claim_store_identity")
        except BaseException:
            db.close()
            raise
        return db

    @classmethod
    def provision(cls, path: Path, runner_id: str):
        """Explicit installer operation; refuses existing files, including links."""
        store = cls(path, runner_id)
        try:
            _private_file(store.path.parent, directory=True)
            fd = os.open(store.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            with closing(sqlite3.connect(store.path.as_uri() + "?mode=rw", uri=True)) as db:
                db.execute("PRAGMA synchronous=FULL")
                with db:
                    db.execute("CREATE TABLE identity (version INTEGER NOT NULL, runner_id TEXT NOT NULL)")
                    db.execute("INSERT INTO identity VALUES (1, ?)", (runner_id,))
                    db.execute("CREATE TABLE claims (task_id TEXT PRIMARY KEY NOT NULL, nonce TEXT UNIQUE NOT NULL)")
            directory_fd = os.open(store.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except (OSError, sqlite3.Error) as exc:
            # Keep partial installation for diagnosis; never silently replace it.
            raise Refusal("claim_store_provision") from exc
        return store

    def claim_task_once(self, task_id: str, nonce: str) -> bool:
        """Call only after Task verification/readback; commit before sandbox work."""
        _identity(task_id)
        if type(nonce) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", nonce):
            raise Refusal("claim_identity")
        try:
            with closing(self._connect()) as db:
                with db:
                    db.execute("INSERT INTO claims (task_id, nonce) VALUES (?, ?)", (task_id, nonce))
        except sqlite3.IntegrityError:
            return False
        except (OSError, sqlite3.Error) as exc:
            raise Refusal("claim_store_unavailable") from exc
        return True
