"""Reuse decoded original facts only within one synchronous read operation.

Authorization, rights, expiry, review state and ownership are never cached.
Each reuse checks the safe file path and its current filesystem identity. No
bytes or verification facts survive the outermost call, including exceptions.
"""
from contextvars import ContextVar
from functools import wraps
import asyncio
import threading
import hashlib
import io
from pathlib import Path
from PIL import Image

_facts = ContextVar('hotel_original_verification_facts', default=None)


def _owner():
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return threading.get_ident(), task


def _active_cache():
    value = _facts.get()
    return value['cache'] if value and value['active'] and value['owner'] == _owner() else None


def original_verification_scope(function):
    @wraps(function)
    def scoped(*args, **kwargs):
        if _active_cache() is not None:
            return function(*args, **kwargs)
        scope = {'owner':_owner(), 'cache':{}, 'active':True}
        token = _facts.set(scope)
        try:
            return function(*args, **kwargs)
        finally:
            scope['active'] = False
            scope['cache'].clear()
            _facts.reset(token)
    return scoped


def _file_identity(media, record):
    name = record.get('cache_file', '')
    path = media.cache.files_dir / name
    if not name or Path(name).name != name or path.is_symlink() or path.resolve().parent != media.cache.files_dir:
        raise ValueError('MEDIA_CACHE_PATH_INVALID')
    stat = path.stat()
    return (str(path), stat.st_dev, stat.st_ino, stat.st_size,
            stat.st_mtime_ns, stat.st_ctime_ns, record['sha256'])


def original_facts(media, record):
    identity = _file_identity(media, record)
    key = (id(media), record['asset_id'], identity)
    cache = _active_cache()
    if cache is not None and key in cache:
        return dict(cache[key])
    raw = media._read_bytes(record)
    with Image.open(io.BytesIO(raw)) as im:
        width, height = im.size
        if width * height > 40000000 or getattr(im, 'n_frames', 1) != 1:
            raise ValueError('invalid image')
        mime = {'JPEG':'image/jpeg', 'PNG':'image/png', 'WEBP':'image/webp'}.get(im.format)
        im.verify()
    with Image.open(io.BytesIO(raw)) as im:
        im.load()
    if _file_identity(media, record) != identity:
        raise ValueError('MEDIA_CACHE_CHANGED_DURING_VERIFICATION')
    facts = {'original_sha256':hashlib.sha256(raw).hexdigest(), 'width':width,
             'height':height, 'byte_size':len(raw), 'mime_type':mime}
    # Bound temporary metadata even for unusually large galleries; overflowing
    # this cap costs extra validation and cannot grant access.
    if cache is not None and len(cache) < 512:
        cache[key] = facts
    return dict(facts)
