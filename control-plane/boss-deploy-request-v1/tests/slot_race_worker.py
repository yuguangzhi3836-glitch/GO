"""One tick's check-and-reserve, in a process of its own -- for the slot race test.

This lives in its own module for one reason: `multiprocessing`'s spawn start method
re-imports the module that contains the target, and the test module imports the Bridge,
which imports `fcntl` unconditionally because the ledger lock is `fcntl.flock`.  On a
host without `fcntl` that import fails in the child, so the child would never reach the
worker at all.  This module imports only the request gate -- which needs no `fcntl` --
and takes its lock with whatever primitive the host actually has.

The lock is taken here rather than borrowed from the Bridge on purpose.  On a Windows
workstation the Bridge's `fcntl` is a no-op stand-in installed by the audit harness, so a
race guarded by *that* would prove nothing.  `fcntl.flock` and `msvcrt.locking` are both
exclusive, non-blocking, and released by the kernel when the descriptor or the process
goes away, which is the discipline `Ledger.held()` applies where it runs for real.  Which
one ran travels with the outcome, so a green result can never be read as more than it is.
"""
import datetime as dt
import json
import os
import pathlib
import sys

try:
    import fcntl
except ImportError:                        # pragma: no cover - POSIX always has it
    fcntl = None
try:
    import msvcrt
except ImportError:                        # pragma: no cover - Windows always has it
    msvcrt = None

PRIMITIVE = "fcntl.flock" if fcntl else ("msvcrt.locking" if msvcrt else None)


def lock(descriptor):
    """Exclusive, non-blocking, or an OSError whose errno says which failure it was."""
    if fcntl is not None:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    if msvcrt is not None:
        # A byte-range lock needs a byte to lock; the lock file is ours and holds
        # nothing, so giving it one costs nothing.
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return
    raise OSError(38, "no file locking primitive on this host")


def run(component, root, slot_path, at_iso, tag, guarded, barrier):
    """Check the environment and reserve it, exactly as the guarded path does.

    In the guarded half the lock is taken before the document is read, so the ordering
    is the lock's and not the scheduler's.  In the unguarded half both processes read
    first and meet at the barrier, which makes the negative control deterministic
    rather than lucky: a test that passes with the lock removed proves nothing.
    """
    sys.path.insert(0, component)
    import go_deploy_request as gate

    at = dt.datetime.fromisoformat(at_iso.replace("Z", "+00:00"))
    descriptor = None
    if guarded:
        descriptor = os.open(str(pathlib.Path(root) / "ledger.lock"),
                             os.O_RDWR | os.O_CREAT, 0o600)
        lock(descriptor)
    try:
        slots = gate.load_environment_slots(slot_path)
        if slots is None:
            slots = gate.activate_environment_guard({}, at)
        if not guarded and barrier is not None:
            barrier.wait(timeout=120)
        try:
            gate.ensure_environment_idle(slots, gate.ENVIRONMENT)
        except gate.Reject as exc:
            outcome = str(exc)
        else:
            gate.reserve_environment(slots, gate.ENVIRONMENT, at, action=gate.ACTION,
                                     request_key=tag, request_id=tag)
            gate.save_environment_slots(slots, slot_path)
            outcome = "reserved"
    finally:
        if descriptor is not None:
            os.close(descriptor)
    (pathlib.Path(root) / ("race-" + tag)).write_text(
        json.dumps({"outcome": outcome, "primitive": PRIMITIVE}), encoding="utf-8")
    return outcome
