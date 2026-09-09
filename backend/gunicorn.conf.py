# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
# Author: Rafael M. Koike & Cursor Agent ("Ada")
"""Gunicorn configuration, derived from the same NVSF_* settings the application reads.

ONE CONFIGURATION SURFACE
-------------------------
Bind address, port and TLS are declared once, in ``config_registry.py``, and read here. The
alternative -- gunicorn flags in the compose command plus NVSF_* for everything else -- produces
the failure where the app believes it is serving on one address and gunicorn is serving on
another, which presents as an OIDC redirect that does not come back.

WHY SYNC WORKERS, AND WHY SO FEW
---------------------------------
Requests here are short. The long work -- clone, scan, reason -- happens in the assessment thread
pool inside a worker process, not in a request. So the web tier does not need concurrency for
throughput; it needs enough workers that one slow request cannot block the health check.

Two, by default, and deliberately not ``2 * cpu + 1``. Each worker runs its own assessment pool
and holds its own SQLite connections, so worker count multiplies both the load on the shared
reasoning endpoint and the write contention on one database file. On a 16-core ITSS VM the
conventional formula would give 33 workers, which is how you rate-limit the endpoint for every
other team using it.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent

# `app:app` is imported by name, and app.py lives in backend/. Setting this here rather than
# relying on the working directory means the same command line works from anywhere.
pythonpath = str(_BACKEND)
chdir = str(_BACKEND)


def _int(name: str, default: int) -> int:
    """An integer setting, falling back rather than crashing the master process.

    A malformed value should not stop the server from starting, because the alternative is a
    container that will not boot over a typo in a tuning knob nobody meant to change.
    """
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


# ── Networking ───────────────────────────────────────────────────────────────────────────────

bind = f"{os.environ.get('NVSF_BIND_ADDR', '127.0.0.1')}:{_int('NVSF_PORT', 8000)}"

# The VM sits behind whatever ITSS puts in front of it, and 128 pending connections is generous
# for an internal tool with a few dozen users.
backlog = 128

certfile = os.environ.get("NVSF_TLS_CERT") or None
keyfile = os.environ.get("NVSF_TLS_KEY") or None

# ── Workers ──────────────────────────────────────────────────────────────────────────────────

workers = _int("NVSF_WEB_WORKERS", 2)
# Never more than the machine can run, in case someone sets the knob optimistically.
workers = min(workers, max(2, multiprocessing.cpu_count()))

# gthread, stated rather than left as "sync": gunicorn silently switches to gthread whenever
# threads > 1, and a worker class that depends on another setting is a surprise waiting for
# whoever next reads this file.
worker_class = "gthread"

# Threads per worker: enough that a slow contract-bundle response cannot make the health check
# time out, and few enough that SQLite write contention stays trivial.
threads = _int("NVSF_WEB_THREADS", 4)

# Longer than a browser would tolerate, because the mapping assistant makes a reasoning call
# inside a request. Still finite: an unbounded timeout turns one hung upstream call into a worker
# that never comes back.
timeout = _int("NVSF_WEB_TIMEOUT_SEC", 300)

graceful_timeout = 30

# Above any sane reverse-proxy idle timeout, so the proxy closes idle connections rather than the
# app closing them underneath a request the proxy is still holding.
keepalive = 65

# Recycle workers periodically. Not because of a known leak -- because a long-lived process
# analysing arbitrary third-party text will eventually accumulate something, and a bounded
# lifetime turns a slow leak into a non-event. Jittered so workers do not all restart together.
max_requests = 1000
max_requests_jitter = 100

# ── Logging ──────────────────────────────────────────────────────────────────────────────────

# stdout/stderr: the container's log stream is the log destination, and the application installs
# its own formatter and redaction filter on top.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("NVSF_LOG_LEVEL", "INFO").lower()

# Includes the request duration, which is the field you want first when someone reports that the
# UI is slow. Query strings are logged: this API puts no secrets in them, and the redaction filter
# covers the case where something changes.
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(a)s"'

# ── Process ──────────────────────────────────────────────────────────────────────────────────

proc_name = "nvsf"

# /dev/shm rather than the default /tmp: on a container with a read-only or slow /tmp, gunicorn's
# heartbeat file can stall and the master kills workers that are perfectly healthy.
#
# Guarded because /dev/shm does not exist on macOS, and gunicorn does not fall back -- it raises
# at worker spawn. Without the guard, this file works in the container and crashes for every
# developer running the production command locally.
worker_tmp_dir = "/dev/shm" if Path("/dev/shm").is_dir() else None  # noqa: S108 - tmpfs


def on_starting(server) -> None:
    """Run the startup gate in the master, before any worker is forked.

    The application already runs the gate at import, so every worker refuses to boot on a bad
    configuration -- and that is not enough. Gunicorn's arbiter does not know that exit code 78
    means "this will never work"; it respawns, the replacement fails identically, and the container
    sits in a tight loop printing the same paragraph. Meanwhile ``docker ps`` says "Up", because
    the master is perfectly healthy. An operator sees a running service that answers nothing.

    Checking here makes a configuration problem what it actually is: a startup failure, reported
    once, with a non-zero exit and no container to misread as running.
    """
    if str(_BACKEND) not in sys.path:
        sys.path.insert(0, str(_BACKEND))

    import config_launch

    config_launch.load_or_exit()

    import startup_gate

    try:
        startup_gate.prepare()
    except startup_gate.StartupRefused as exc:
        # print, not server.log: this must be legible in `docker logs` as the last thing before
        # the exit, not wrapped in a log line format an operator has to read past.
        print(f"\nnvis-software-factory: {exc}\n", file=sys.stderr, flush=True)
        raise SystemExit(78) from exc  # EX_CONFIG

    server.log.info(
        "nvsf: binding %s with %d worker(s) x %d thread(s), tls=%s",
        bind, workers, threads, "on" if certfile else "off",
    )


def worker_int(worker) -> None:
    """Log which worker was interrupted, on SIGINT/SIGQUIT.

    Without this, a worker killed for exceeding ``timeout`` leaves nothing but gunicorn's generic
    message, and there is no way to tell afterwards which request was responsible.
    """
    worker.log.warning("nvsf: worker %s interrupted", worker.pid)
