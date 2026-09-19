"""The fixed Hong Kong media mount (WP-9, product decision of 2026-09-19).

> **Every path that recreates the eight business containers mounts the fixed media
> directory, and reports whether it did.**

The media cache is the one thing on this host a deployment cannot reconstruct:
``/var/lib/go-hotel/media-cache``, holding ``index.sqlite3`` and ``files/``, written by
the hotel application and shipped by no candidate. It is *fixed infrastructure*, not a
property of a version. No candidate declares it, signs it, carries it or negotiates it,
and no candidate decides whether it is mounted or points it somewhere else.

What makes the loss quiet is the application's own fallback. ``media_harvester``
resolves its cache as ``os.getenv("GO_MEDIA_CACHE_DIR", "var/media_cache")``, so an image
that comes up **without** the mount does not fail: it creates a container-local cache,
writes there, and the real directory is orphaned -- intact on disk, read by nothing.
Nothing errors, and nothing is ever deleted. The forbidden thing is therefore not
"deleting the directory" but "not mounting it", which is why forbidding deletion protects
nothing and why the check below reads the running containers rather than the command line.

This module owns three things, once, for every recreating path:

* **the single definition** -- the fixed host path, the fixed container path, the
  environment variable the application resolves it through, and the eight services.
  Declared here and nowhere else. No caller supplies a path, a service list, a mount
  option or an expected value.
* **the command builder** -- ``recreate_argv()`` writes the fixed mount into the Compose
  invocation as an overlay generated from that definition. ``deploy``, ``rollback`` and
  anything else that recreates the business containers calls ``recreate()``, so there is
  one injection point rather than one per entry.
* **the post-start check** -- ``verify()`` reads the containers that are actually running
  and answers ``MEDIA_MOUNT=SUCCESS`` or raises with a reason. A command line that
  mentions a mount proves nothing; the state Docker applied is what is checked.

Docker bind mounts are fixed when a container is created and cannot be added to a running
one, so the order is not a preference: mount at create, then check, then report. That is
also why ``verify()`` runs after the recreation and never before it.

``MEDIA_MOUNT=SUCCESS`` is one of the conditions of a successful operation. A failure
raises ``MediaMountFailed``, whose ``gate_results`` carry ``MEDIA_MOUNT=FAILED`` and
``MEDIA_MOUNT_REASON``, so no caller can report a plain success for an operation that left
the media directory unmounted.
"""
import hashlib
import json
import os
import pathlib
import tempfile

DOCKER = '/usr/bin/docker'
PROJECT = 'go-822-staging'
COMPOSE = '/home/go-stg/releases/r31-5-final-completion-20260906/GO_HYATT_DIRECT_BOOKING_R3_1_5_TEST_BOOTSTRAP_IDENTITY_FIX_20260906/deploy/docker-compose.r31-hk-staging.yml'
ENV_FILE = '/home/go-stg/control/r317-five-star-completeness-20260828/runtime.env'
SERVICES = ('api', 'recovery-worker', 'outbox-worker', 'mobile-push-receipt-worker',
            'reconciliation-worker', 'mobile-push-worker', 'mobile-engagement-worker',
            'judgment-worker')

# The infrastructure. One host path, one container path, and they are the same directory:
# the eight services read the host's cache through a bind mount at its own path, so the
# application needs no knowledge that it is mounted at all.
HOST_PATH = '/var/lib/go-hotel/media-cache'
CONTAINER_PATH = HOST_PATH
CACHE_ENV = 'GO_MEDIA_CACHE_DIR'
# Docker must never invent the directory. `create_host_path: false` makes a missing host
# path a failure of the recreation rather than a silently empty cache.
CREATE_HOST_PATH = False
# The overlay is generated per operation beside the deploy image override, in the same
# executor-owned tmpfs directory, and removed in a `finally`.
OVERLAY_DIR = '/run/go-hk-deployctl'

# The result vocabulary. Two words, and the operation's own status is the caller's.
MEDIA_MOUNT = 'MEDIA_MOUNT'
MEDIA_MOUNT_REASON = 'MEDIA_MOUNT_REASON'
SUCCESS = 'SUCCESS'
FAILED = 'FAILED'

# One code per way the mount can fail, because an operator answers them differently.
E_MEDIA_MOUNT_CONTAINERS = 'E_MEDIA_MOUNT_CONTAINERS'
E_MEDIA_MOUNT_ABSENT = 'E_MEDIA_MOUNT_ABSENT'
E_MEDIA_MOUNT_ENV_DRIFT = 'E_MEDIA_MOUNT_ENV_DRIFT'
E_MEDIA_MOUNT_INACCESSIBLE = 'E_MEDIA_MOUNT_INACCESSIBLE'
E_MEDIA_MOUNT_PROBE_UNAVAILABLE = 'E_MEDIA_MOUNT_PROBE_UNAVAILABLE'

# The in-container accessibility probe. `python` is not an assumption this module makes:
# it is what the runtime image already is -- the Compose file's health check for `api` is
# `python -c 'import urllib.request; ...'` and every worker's command is
# `python -m go_hotel.workers.<name>`. The probe lists the mounted directory, which fails
# if the mount is missing, if it resolved to an image-baked empty directory, or if the
# directory is present but not readable by the container's user.
PROBE = ("import os,sys\n"
         "try:\n"
         "    os.listdir(sys.argv[1])\n"
         "except OSError:\n"
         "    sys.exit(7)\n"
         "sys.exit(0)\n")
# 126/127 are the shell's "found but not executable" / "not found", and are read as a
# broken probe rather than as an inaccessible directory: reporting the second when the
# first is true would blame the media directory for something it did not do.
PROBE_UNAVAILABLE_EXIT_CODES = (126, 127)


class MediaMountFailed(ValueError):
    """A refusal carrying the reason, and the gate results that must reach the record.

    The message is the stable code, so it survives as the failure document's
    `error_code` in the same shape as every other executor refusal. The mapping is what
    a caller merges into `gate_results`, so `MEDIA_MOUNT=FAILED` and its reason are
    reported rather than inferred from a sentence.
    """

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason
        self.gate_results = {MEDIA_MOUNT: FAILED, MEDIA_MOUNT_REASON: reason}


def overlay_text():
    """The Compose overlay that carries the fixed mount, built from the definition.

    Every service gets the same two keys: the environment the application resolves the
    cache through, and the bind mount. Both are written here rather than in a file kept
    in the repository, because the definition is this host's and the overlay exists only
    for the length of one operation.
    """
    lines = ['services:\n']
    for service in SERVICES:
        lines.append('  ' + service + ':\n')
        lines.append('    environment:\n')
        lines.append('      ' + CACHE_ENV + ': ' + CONTAINER_PATH + '\n')
        lines.append('    volumes:\n')
        lines.append('      - type: bind\n')
        lines.append('        source: ' + HOST_PATH + '\n')
        lines.append('        target: ' + CONTAINER_PATH + '\n')
        lines.append('        bind:\n')
        lines.append('          create_host_path: ' + ('true' if CREATE_HOST_PATH else 'false') + '\n')
    return ''.join(lines)


def overlay_sha256():
    """The digest of the overlay this module would write, for tests and audit."""
    return hashlib.sha256(overlay_text().encode('utf-8')).hexdigest()


def write_overlay(directory=None):
    """Write the overlay where the executor may write, and return its path.

    Same shape as the deploy image override: created `0600`, exclusive, in the
    executor's own tmpfs directory, and removed by `recreate()` in a `finally`. It
    holds no secret and is regenerated every time, so nothing can be stale or tampered
    with between operations without the bytes themselves showing the change.

    `directory` is read at call time rather than bound as a default, so `OVERLAY_DIR`
    is the single place the location is decided -- a default argument would freeze the
    path at import and quietly ignore any later reassignment of the constant.
    """
    root = pathlib.Path(OVERLAY_DIR if directory is None else directory)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix='media-mount-', suffix='.yaml', dir=str(root), text=True)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(overlay_text())
    return path


def remove_overlay(path):
    """Remove the generated overlay. The only unlink in this module, and never the cache."""
    try:
        os.unlink(path)
    except OSError:
        pass


def recreate_argv(overlay, extra_files=()):
    """The one Compose command that recreates the eight business containers.

    Every recreating entry point calls this instead of assembling a command, so the
    fixed mount cannot be omitted by one of them remembering differently. The media
    overlay is the **last** `-f`, so its two keys are the final word: no earlier file,
    and no candidate-supplied file, can turn the mount off or move it.
    """
    argv = [DOCKER, 'compose', '--env-file', ENV_FILE, '-p', PROJECT, '-f', COMPOSE]
    for extra in extra_files:
        argv += ['-f', extra]
    argv += ['-f', overlay, 'up', '-d', '--no-deps', '--force-recreate', *SERVICES]
    return argv


def _read(runner, argv):
    out = runner.run(argv)
    if getattr(out, 'returncode', None) != 0:
        raise MediaMountFailed(E_MEDIA_MOUNT_CONTAINERS)
    return getattr(out, 'stdout', '')


def running_inventory(runner):
    """The eight services' containers, as Docker reports them right now."""
    ids = []
    for service in SERVICES:
        raw = _read(runner, [DOCKER, 'ps', '-q',
                             '--filter', 'label=com.docker.compose.project=' + PROJECT,
                             '--filter', 'label=com.docker.compose.service=' + service])
        found = [value for value in raw.splitlines() if value]
        if len(found) != 1:
            raise MediaMountFailed(E_MEDIA_MOUNT_CONTAINERS)
        ids.append(found[0])
    raw = _read(runner, [DOCKER, 'inspect', *ids])
    try:
        data = json.loads(raw)
    except Exception as exc:
        raise MediaMountFailed(E_MEDIA_MOUNT_CONTAINERS) from exc
    if not isinstance(data, list) or len(data) != len(SERVICES):
        raise MediaMountFailed(E_MEDIA_MOUNT_CONTAINERS)
    return data


def probe_argv(container_id):
    """Ask one container whether the fixed directory is readable inside it."""
    return [DOCKER, 'exec', container_id, 'python', '-c', PROBE, CONTAINER_PATH]


def probe_container(runner, container_id):
    """The probe's exit code, which is data rather than an error."""
    out = runner.run(probe_argv(container_id))
    return getattr(out, 'returncode', None)


def _under(path, root):
    """Whether a container path is ``root`` or sits inside it."""
    return path == root or path.startswith(root.rstrip('/') + '/')


def judge(inventory, probes):
    """The verdict over inspected containers and probe exit codes. Pure.

    Split out from `verify()` so the four questions can be asked of a fixture without a
    Docker host: the containers exist and are running, the fixed container path is a
    bind mount from the fixed host path and read-write, the application resolves the
    cache there and nowhere else, and the directory is readable inside the container.
    """
    if not isinstance(inventory, list) or len(inventory) != len(SERVICES):
        raise MediaMountFailed(E_MEDIA_MOUNT_CONTAINERS)
    seen = {}
    for row in inventory:
        if not isinstance(row, dict):
            raise MediaMountFailed(E_MEDIA_MOUNT_CONTAINERS)
        config = row.get('Config') or {}
        labels = config.get('Labels') or {}
        service = labels.get('com.docker.compose.service')
        if (service not in SERVICES or service in seen
                or labels.get('com.docker.compose.project') != PROJECT):
            raise MediaMountFailed(E_MEDIA_MOUNT_CONTAINERS)
        if (row.get('State') or {}).get('Running') is not True:
            raise MediaMountFailed(E_MEDIA_MOUNT_CONTAINERS)
        environment = [value.split('=', 1)[1] for value in (config.get('Env') or [])
                       if value.startswith(CACHE_ENV + '=')]
        if environment != [CONTAINER_PATH]:
            # Exactly one value, and it is the fixed path. A container resolving the cache
            # anywhere else -- including nowhere, via the application's relative default --
            # is a container whose media writes never reach the cache.
            raise MediaMountFailed(E_MEDIA_MOUNT_ENV_DRIFT)
        mounts = [mount for mount in (row.get('Mounts') or []) if isinstance(mount, dict)]
        at_path = [mount for mount in mounts
                   if str(mount.get('Destination') or '') == CONTAINER_PATH]
        if len(at_path) != 1:
            # Absent, or doubled. Both mean the eight services are not reading the cache
            # as one directory.
            raise MediaMountFailed(E_MEDIA_MOUNT_ABSENT)
        mount = at_path[0]
        if (mount.get('Type') != 'bind' or mount.get('Source') != HOST_PATH
                or mount.get('Destination') != CONTAINER_PATH or mount.get('RW') is not True):
            raise MediaMountFailed(E_MEDIA_MOUNT_ABSENT)
        for other in mounts:
            if other is mount:
                continue
            if (_under(str(other.get('Destination') or ''), CONTAINER_PATH)
                    or _under(str(other.get('Source') or ''), HOST_PATH)):
                # Something mounted inside the cache, or out of it, shadows part of the
                # directory the services are supposed to be reading whole.
                raise MediaMountFailed(E_MEDIA_MOUNT_ABSENT)
        code = probes.get(row.get('Id'))
        if code != 0:
            raise MediaMountFailed(E_MEDIA_MOUNT_PROBE_UNAVAILABLE
                                   if code in PROBE_UNAVAILABLE_EXIT_CODES
                                   else E_MEDIA_MOUNT_INACCESSIBLE)
        seen[service] = True
    if set(seen) != set(SERVICES):
        raise MediaMountFailed(E_MEDIA_MOUNT_CONTAINERS)
    return {MEDIA_MOUNT: SUCCESS}


def verify(runner):
    """Check the running containers and report, or raise with the reason.

    Runs after the recreation. Reading the containers rather than the command line is
    the whole point: a correct `-f` that Docker then failed to apply looks identical on
    the command line and nothing like it in `docker inspect`.
    """
    inventory = running_inventory(runner)
    probes = {row.get('Id'): probe_container(runner, row.get('Id')) for row in inventory}
    return judge(inventory, probes)


def recreate(runner, run, extra_files=()):
    """Recreate the business containers with the fixed mount, then check it. One door.

    `run(argv)` is the caller's own executor wrapper, because the deploy path and the
    rollback path have different runner helpers and timeouts; everything that decides
    *what* runs -- and everything that checks it afterwards -- is here. Raises
    `MediaMountFailed` when the mount is not in place, so an operation that lost the
    media directory cannot return a plain success.
    """
    overlay = write_overlay()
    try:
        run(recreate_argv(overlay, extra_files=extra_files))
    finally:
        remove_overlay(overlay)
    return verify(runner)


# The one injection point, named so it can be found rather than remembered:
#
#     result = media_mount.recreate(runner, run)      # deploy, rollback, and future paths
#     ...merge `result` into this operation's gate results...
#
# A recreating path that builds its own Compose command instead of calling this one is
# the failure this module exists to make impossible; the suite asserts that no other
# file in the tree contains the recreation flags.
RECREATE_SEAM = 'deploy_runtime.run_deploy / rollback_runtime.run_rollback -> media_mount.recreate'
