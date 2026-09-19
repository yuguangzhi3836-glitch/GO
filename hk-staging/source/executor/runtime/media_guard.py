"""The Hong Kong executor's media-preservation gate (CCV1-95 WP-9 phase 1).

> **A deployment may not be able to lose the media cache.**

The media cache is the only state on this host that a deployment cannot reconstruct.
It lives in a host directory -- ``/var/lib/go-hotel/media-cache``, holding
``index.sqlite3`` and ``files/`` -- which the eight business services read through a
bind mount at the same path.  Nothing in the repository is that data, and nothing in a
deployment regenerates it.

What makes the loss *quiet* is the application's own fallback.  ``media_harvester``
resolves its cache as ``os.getenv("GO_MEDIA_CACHE_DIR", "var/media_cache")``, so an
image that comes up **without** the mount does not fail: it creates a container-local
cache, writes there, and the real one is orphaned -- intact on disk and no longer
read by anything.  A deployment that replaces the compose file, drops the mount, or
points it somewhere else therefore loses the media cache without producing an error
anyone would see.  That is the deployment this module refuses.

The gate is two questions, asked on either side of the mutation:

* **before** -- which storage is the media cache, if any?  The answer is the
  directory's ``st_dev`` and ``st_ino``.  The identity of the *directory*, not a digest
  of its contents: the cache is written through during normal operation, so its bytes
  are expected to change and hashing them would refuse every healthy deployment.
* **after** -- is it the same storage, *and* are the eight services actually reading
  it?  Both halves are required.  A cache that survived untouched but is no longer
  mounted is precisely the loss above, so a preserved identity with a missing mount
  refuses.  The mount answer is read off the running containers: one bind mount whose
  source and destination are both the cache path, read-write, with
  ``GO_MEDIA_CACHE_DIR`` pointing at it.  No caller supplies a path, a service list or
  an expected identity; they are fixed here.

Borrowed from the Hong Kong media-topology line (``media_topology_runtime.py`` on boss
PR #201) and deliberately not copied from it.  That module binds media preservation to
a topology *descriptor inside the candidate contract* (``go.hk-candidate-contract.v3``)
and to a v1-to-v2 first-install transition with its own marker, installation document
and authorization artifact.  The converged baseline retires that shape: WP-1 makes
``go.release-candidate.v1`` the only candidate identity and states that a topology
implementation hash is not part of it.  So what is taken is the *property* -- a storage
identity checked either side of the mutation, fail-closed -- and not the mechanism.
This module has no marker file, no installation document, no authorization artifact and
no transition state, because none of them is needed to answer "is this the same
storage", and each of them would be a second place where the answer could come from a
file instead of from the host.

**What this gate can and cannot claim.**  It can refuse a deployment that would leave
the cache unmounted, moved, or replaced.  It cannot claim preservation for a cache that
was already gone when the deployment started: with no identity to compare, the result
is ``NOT_ACTIVE``, never ``PASS``.  It also does not read or write the cache's bytes,
and it performs no filesystem mutation of any kind.
"""
import os
import pathlib
import stat

# The cache, the fixed set of leaf names a healthy one carries, and the environment
# variable the application resolves it through.  Declared here rather than imported so
# that this module can be loaded by a deploy path that has no candidate fact, and pinned
# equal to `deploy_runtime.SERVICES` by the guard's suite.
CACHE = '/var/lib/go-hotel/media-cache'
CONTENTS = ('index.sqlite3', 'files')
CACHE_ENV = 'GO_MEDIA_CACHE_DIR'
SERVICES = ('api', 'recovery-worker', 'outbox-worker', 'mobile-push-receipt-worker',
            'reconciliation-worker', 'mobile-push-worker', 'mobile-engagement-worker',
            'judgment-worker')
PROJECT = 'go-822-staging'

# Three codes, and no fourth spelling for any of them.
E_MEDIA_STORAGE_ABSENT = 'E_MEDIA_STORAGE_ABSENT'
E_MEDIA_MOUNT_DRIFT = 'E_MEDIA_MOUNT_DRIFT'
E_MEDIA_STORAGE_IDENTITY_DRIFT = 'E_MEDIA_STORAGE_IDENTITY_DRIFT'

# The two outcomes.  `NOT_ACTIVE` exists so that "there was no cache to preserve" is a
# distinct, observable answer rather than something that can be read as a pass.
PRESERVED = 'PASS'
NOT_ACTIVE = 'NOT_ACTIVE'

# The `gate_results` keys this module contributes.  Every value is `PRESERVED`, so the
# deploy Evidence stays within the rule that a gate result is `PASS` or `False`; the
# storage identity is a structured fact and belongs in the deploy record instead.
GATE_KEYS = ('media_persistence', 'media_mounts')


class Reject(ValueError):
    """A refusal, carrying one of the three stable codes as its message."""


def _require_directory_and_trusted_ancestors(path):
    """The cache path and every ancestor must be real directories, not symlinks.

    A symlinked cache -- or a symlinked ancestor -- is refused because it makes "the
    same storage" unanswerable: ``lstat`` would report the link, ``stat`` would report
    whatever it currently resolves to, and a deployment that swapped the link would
    read as a different directory without anything having moved.

    This walks with ``lstat`` rather than opening each component with ``O_NOFOLLOW``.
    The walk is a *detection* gate, not a hardened reader, because this module never
    reads a byte out of the cache: what it protects is which directory the deployment
    points the services at, and a swap between this check and the comparison below is
    caught by the comparison itself, which re-reads the identity after the mutation.
    """
    candidate = pathlib.Path(path)
    for ancestor in (candidate, *candidate.parents):
        try:
            info = ancestor.lstat()
        except OSError as exc:
            raise Reject(E_MEDIA_STORAGE_ABSENT) from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise Reject(E_MEDIA_STORAGE_ABSENT)


def storage_identity():
    """The storage the media cache is on, or ``None`` when there is no cache at all.

    ``None`` is the honest answer for a host without a cache, and it is deliberately
    distinguished from a refusal: a refusal means the cache is there but cannot be
    shown to be a plain directory, which is a deployment that must not proceed.
    """
    if not os.path.lexists(CACHE):
        # `lexists`, not `exists`: a dangling symlink at the cache path is present and
        # wrong, not absent, and must not be read as "no cache here".
        return None
    _require_directory_and_trusted_ancestors(CACHE)
    info = os.stat(CACHE)
    contents = sorted(name for name in CONTENTS if os.path.lexists(os.path.join(CACHE, name)))
    if tuple(contents) != tuple(sorted(CONTENTS)):
        # A directory at the cache path that is missing a leaf is not this host's
        # cache; it is something else wearing the path, and saying so is the point.
        raise Reject(E_MEDIA_STORAGE_ABSENT)
    return {'host_path': CACHE, 'device': info.st_dev, 'inode': info.st_ino,
            'contents': list(contents)}


def _under(path, root):
    """Whether a container path is ``root`` or sits inside it."""
    return path == root or path.startswith(root.rstrip('/') + '/')


def _service_mounts(container):
    """The cache mounts and the cache environment a single container carries.

    A mount is this module's business if either end of it touches the cache: one
    mounted *at* the cache path, one mounted *inside* it (which shadows part of the
    cache without replacing it, and is easy to miss), or one *from* it to somewhere
    else.  All three mean the eight services are not reading the cache as one
    directory, which is the fact being established.
    """
    config = container.get('Config') or {}
    labels = config.get('Labels') or {}
    environment = [value.split('=', 1)[1] for value in (config.get('Env') or [])
                   if value.startswith(CACHE_ENV + '=')]
    mounts = []
    for mount in (container.get('Mounts') or []):
        destination = str(mount.get('Destination') or '')
        source = str(mount.get('Source') or '')
        if _under(destination, CACHE) or _under(source, CACHE):
            mounts.append(mount)
    return labels, environment, mounts


def require_mounts(inventory, expected_image):
    """The eight services must be reading the cache, and nothing else. Refuses otherwise.

    Every way the mount can be wrong is the same refusal: absent, doubled, shadowed by
    a second mount over the same path, pointing at a different host directory, mounted
    read-only, or masked by an environment that resolves the cache somewhere else.
    They are one code because they call for one action -- do not deploy this.
    """
    if not isinstance(inventory, list) or len(inventory) != len(SERVICES):
        raise Reject(E_MEDIA_MOUNT_DRIFT)
    seen = {}
    for container in inventory:
        if not isinstance(container, dict):
            raise Reject(E_MEDIA_MOUNT_DRIFT)
        labels, environment, mounts = _service_mounts(container)
        service = labels.get('com.docker.compose.service')
        if (service not in SERVICES or service in seen
                or labels.get('com.docker.compose.project') != PROJECT):
            raise Reject(E_MEDIA_MOUNT_DRIFT)
        if container.get('Image') != expected_image:
            raise Reject(E_MEDIA_MOUNT_DRIFT)
        if environment != [CACHE]:
            # Exactly one value, and it is the cache. A container that resolves the
            # cache anywhere else -- including nowhere, via the application's relative
            # default -- is a container whose media writes do not reach the cache.
            raise Reject(E_MEDIA_MOUNT_DRIFT)
        if len(mounts) != 1:
            raise Reject(E_MEDIA_MOUNT_DRIFT)
        mount = mounts[0]
        if (mount.get('Type') != 'bind' or mount.get('Source') != CACHE
                or mount.get('Destination') != CACHE or mount.get('RW') is not True):
            raise Reject(E_MEDIA_MOUNT_DRIFT)
        seen[service] = True
    if set(seen) != set(SERVICES):
        raise Reject(E_MEDIA_MOUNT_DRIFT)
    return PRESERVED


def before(inventory, expected_image):
    """What this host holds, and how it is being read, before anything is mutated.

    Returns the pair the ``after`` comparison needs, under the same key names ``after``
    reports, so that one value can be carried from before to after and into the record
    without being renamed on the way.  ``media_mounted_before`` is recorded rather than
    required: a host whose cache exists but is not yet mounted is a host that is being
    *brought* onto the cache, and refusing that would make first activation impossible.
    What the deployment must not do is end unmounted, which is ``after``'s question.
    """
    identity = storage_identity()
    if identity is None:
        return {'media_storage_identity': None, 'media_mounted_before': False}
    mounted = True
    try:
        require_mounts(inventory, expected_image)
    except Reject:
        mounted = False
    return {'media_storage_identity': identity, 'media_mounted_before': mounted}


def after(state, inventory, expected_image):
    """The verdict, read off the host after the mutation.

    Both halves are required, and the order is not arbitrary: the mount question is
    asked first, because a cache that is no longer read by the eight services is the
    loss even when its directory is untouched.
    """
    if not isinstance(state, dict) or 'media_storage_identity' not in state:
        raise Reject(E_MEDIA_STORAGE_IDENTITY_DRIFT)
    identity = storage_identity()
    if state['media_storage_identity'] is None:
        # There was nothing to preserve, so nothing can be claimed as preserved. If the
        # deployment brought a cache onto this host, the mount is still required of it.
        if identity is not None:
            require_mounts(inventory, expected_image)
        return {'media_persistence': NOT_ACTIVE, 'media_mounts': PRESERVED,
                'media_storage_identity': identity}
    require_mounts(inventory, expected_image)
    if identity is None:
        # There was a cache and now there is not. That is not the same finding as "a
        # different directory stands where it stood", and an operator answers the two
        # differently: one has to be restored, the other has to be explained.
        raise Reject(E_MEDIA_STORAGE_ABSENT)
    if identity != state['media_storage_identity']:
        raise Reject(E_MEDIA_STORAGE_IDENTITY_DRIFT)
    return {'media_persistence': PRESERVED, 'media_mounts': PRESERVED,
            'media_storage_identity': identity}


def gates(result):
    """The `PASS`-valued subset of an ``after`` result, for the deploy's gate results."""
    return {key: result[key] for key in GATE_KEYS if key in result}


def record_fields(value):
    """The storage identity a deploy record carries.

    A fact about this host rather than a verdict, so it goes into the record -- which a
    later rollback reads to learn which storage a deployment ran against -- and not into
    ``gate_results``, where a structured value would violate the rule that a gate result
    is ``PASS`` or ``False``.  Accepts either the ``before`` state or the ``after``
    result, because both name the identity under the same key.

    An absent cache is recorded as an explicit ``None`` rather than omitted: ``null``
    means "there was no cache", and never "unknown, but probably fine".
    """
    return {'media_storage_identity': value.get('media_storage_identity')}


# The seam a wired `run_deploy()` uses, named so it can be found rather than remembered:
#
#     state = media_guard.before(pre_deploy_inventory, candidate)
#     ... the mutation ...
#     result = media_guard.after(state, post_deploy_inventory, candidate)
#
WIRING_SEAM = 'deploy_runtime.run_deploy -> media_guard.before/after'
