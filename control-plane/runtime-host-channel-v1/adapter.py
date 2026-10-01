"""Trusted offline adapter boundaries. Not installed in the live HK Bridge."""
import os
import stat
import time
from pathlib import Path
from channel import Reject, Registry, decode, fields, identifier, window, digest, ACTION


def protected_read(path, max_bytes=16384):
    """Open every component without symlink traversal; require root/no group writes.
    Parent directory file descriptors avoid path replacement between checks/open.
    """
    p = Path(path)
    if not p.is_absolute() or '..' in p.parts:
        raise Reject('absolute_protected_path_required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(p.parts[1:]):
            last = index == len(p.parts[1:]) - 1
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if not last:
                flags |= os.O_DIRECTORY
            newfd = os.open(part, flags, dir_fd=fd)
            os.close(fd); fd = newfd
            st = os.fstat(fd)
            if st.st_uid != 0 or st.st_mode & 0o022:
                raise Reject('unsafe_owner_or_mode')
            if last and not stat.S_ISREG(st.st_mode):
                raise Reject('not_regular')
        raw = os.read(fd, max_bytes + 1)
        if len(raw) > max_bytes:
            raise Reject('size')
        return raw
    except OSError as exc:
        raise Reject('protected_read') from exc
    finally:
        os.close(fd)


def derive_probe(raw, reg, authenticated_author, allowed_authors, now, task_id, nonce):
    """Called only after existing Bridge has authenticated immutable Request PR.
    No host, command or digest comes from Request. IDs/nonce from CC's durable ledger.
    This is NOT a public API: author/head authentication remains the Bridge's job.
    """
    if authenticated_author not in allowed_authors:
        raise Reject('author')
    request = decode(raw)
    fields(request, 'version request_id action environment issued_at expires_at')
    if type(request['version']) is not int or request['version'] != 1:
        raise Reject('version')
    identifier(request['request_id']); identifier(task_id); identifier(nonce)
    window(request, now, 300); window(reg, now, 86400)
    if request['action'] != ACTION or request['environment'] != reg['environment']:
        raise Reject('request_scope')
    return dict(version=1,kind='runtime-host-task',task_id=task_id,nonce=nonce,
                environment=reg['environment'],host_id=reg['host_id'],agent_id=reg['agent_id'],
                generation=reg['generation'],registration_sha256=digest(reg),action=ACTION,
                parameters={},issued_at=now,expires_at=min(now+300,request['expires_at'],reg['expires_at']))
