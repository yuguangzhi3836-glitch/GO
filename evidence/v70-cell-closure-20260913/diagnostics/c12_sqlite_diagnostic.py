"""Read-only trace instrumentation for an isolated pytest database.

No application patches or worker disabling. Logs inode changes across the
existing reset path and outstanding expiration-worker threads.
"""
import json
import logging
import os
from pathlib import Path
import threading
import time

from sqlalchemy import event

TRACE = logging.getLogger("c12.sqlite.diagnostic")
_node = "collection"


def emit(kind, **data):
    TRACE.info(json.dumps({"monotonic_ns": time.monotonic_ns(), "kind": kind,
                          "node": _node, "thread": threading.current_thread().name, **data}, sort_keys=True))


def inode(path):
    try:
        return os.stat(path).st_ino
    except FileNotFoundError:
        return None


def pytest_configure(config):
    TRACE.setLevel(logging.INFO)
    TRACE.propagate = False
    TRACE.addHandler(logging.FileHandler(os.environ["C12_TRACE_PATH"], mode="w"))
    from go_hotel.db.session import engine
    from go_hotel.workers import vertical_expiry_worker

    live_db = str(engine.url.database)
    original_unlink = Path.unlink

    def traced_unlink(path, *args, **kwargs):
        if str(path) == live_db:
            emit("RESET_UNLINK", inode=inode(live_db))
        return original_unlink(path, *args, **kwargs)

    Path.unlink = traced_unlink
    original_expire = vertical_expiry_worker.expire_due

    def traced_expire(*args, **kwargs):
        emit("WORKER_START", inode=inode(live_db))
        try:
            return original_expire(*args, **kwargs)
        finally:
            emit("WORKER_END", inode=inode(live_db))

    vertical_expiry_worker.expire_due = traced_expire

    @event.listens_for(engine, "connect")
    def connect(dbapi_conn, record):
        record.info["c12_inode"] = inode(live_db)
        emit("CONNECT", connection=id(dbapi_conn), inode=record.info["c12_inode"])

    @event.listens_for(engine, "checkout")
    def checkout(dbapi_conn, record, proxy):
        opened_inode = record.info.get("c12_inode")
        current_inode = inode(live_db)
        emit("STALE_CHECKOUT" if opened_inode != current_inode else "CHECKOUT",
             connection=id(dbapi_conn), opened_inode=opened_inode, current_inode=current_inode)

    @event.listens_for(engine, "checkin")
    def checkin(dbapi_conn, record):
        emit("CHECKIN", connection=id(dbapi_conn), opened_inode=record.info.get("c12_inode"), current_inode=inode(live_db))

    @event.listens_for(engine, "engine_disposed")
    def disposed(_engine):
        emit("DISPOSE", inode=inode(live_db))

    @event.listens_for(engine, "handle_error")
    def failed(context):
        original = context.original_exception
        fds = {}
        for name in os.listdir("/proc/self/fd"):
            try:
                target = os.readlink("/proc/self/fd/" + name)
                if live_db in target:
                    fds[name] = target
            except FileNotFoundError:
                pass
        emit("SQL_ERROR", error=str(original), code=getattr(original, "sqlite_errorcode", None),
             name=getattr(original, "sqlite_errorname", None), inode=inode(live_db), fds=fds)


def pytest_runtest_setup(item):
    global _node
    _node = item.nodeid
    emit("TEST_SETUP")


def pytest_runtest_teardown(item, nextitem):
    emit("TEST_TEARDOWN")
