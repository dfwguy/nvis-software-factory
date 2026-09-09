# syntax=docker/dockerfile:1.7
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
#
# Dockerfile — NVIS Software Factory, one image serving API, SPA and docs.
# Author: Rafael M. Koike & Cursor Agent ("Ada")
#
# THREE BUILD STAGES, ONE RUNTIME
# -------------------------------
# Node and Sphinx are build-time tools. Neither belongs in the runtime image: Node alone is
# several hundred megabytes of attack surface for something that produced its output before the
# container ever ran.
#
# Docs are built into the image rather than published separately, so a deployment's documentation
# is always the documentation for the code running there. The app serves them at /docs.
#
# THE RUNTIME HAS git AND NOTHING ELSE IT DOES NOT NEED
# ------------------------------------------------------
# `git` is a genuine runtime dependency -- acquisition shallow-clones the repository under
# assessment. Repository code is never executed, so no language toolchain is needed to analyse it,
# and none is installed.


# ── Stage 1: the SPA ─────────────────────────────────────────────────────────────────────────
FROM node:24-slim AS spa

WORKDIR /build/frontend

# Manifests first. This layer is cached until a dependency actually changes, which is what makes
# an edit to a component a ten-second rebuild rather than a two-minute one.
COPY frontend/package.json frontend/package-lock.json ./
# `npm ci` for the lockfile exactly; `--ignore-scripts` because a postinstall script in a
# transitive dependency should not get to run arbitrary code in the build.
RUN npm ci --ignore-scripts

COPY frontend/ ./
# tsc -b runs first via the build script: a type error fails the image build rather than shipping.
RUN npm run build


# ── Stage 2: the documentation ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS docs

WORKDIR /build

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY docs/requirements.txt docs/requirements.txt
COPY backend/requirements.txt backend/requirements.txt
# conf.py imports from backend/ to read the published contract version, so both sets are needed.
RUN pip install --no-cache-dir -r docs/requirements.txt -r backend/requirements.txt

COPY . .

# -W: a warning here is a broken cross-reference or a page missing from the toctree, and both are
# 404s for a reader. Failing the image build is the right response.
RUN sphinx-build -W --keep-going -b html docs static/docs


# ── Stage 3: runtime ─────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Read at build time by CI and stamped into the image. An operator asking "what is deployed" gets
# an answer from `docker inspect` rather than from a changelog someone remembered to update.
ARG NVSF_BUILD_SHA=unknown
ARG NVSF_BUILD_TIME=unknown

LABEL org.opencontainers.image.title="NVIS Software Factory" \
      org.opencontainers.image.vendor="NVIDIA Corporation" \
      org.opencontainers.image.revision="${NVSF_BUILD_SHA}" \
      org.opencontainers.image.created="${NVSF_BUILD_TIME}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    NVSF_BUILD_SHA=${NVSF_BUILD_SHA}

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends \
        git \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# A fixed UID, not a name. The data directory is a bind mount owned by this UID on the host, and
# `chown 10001` in the deploy guide only means anything if the number is stable across rebuilds.
RUN groupadd --gid 10001 nvsf \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin nvsf

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Everything the application reads at runtime. Copied explicitly rather than with `COPY . .` so
# that adding a directory to the repository is a deliberate decision about whether it ships:
# .git, node_modules, docs sources and the test suite have no business in a runtime image.
COPY backend/ backend/
COPY contracts/ contracts/
COPY standards/ standards/
COPY bin/ bin/
COPY --from=spa /build/static/spa static/spa
COPY --from=docs /build/static/docs static/docs

# Owned by root, readable by nvsf, writable by nobody. The application's only writable path is the
# data directory, which is a mount -- so a compromised worker cannot rewrite the code that runs on
# the next restart. This is durability criterion D1 read the other way round.
RUN chown -R root:root /app && chmod -R a-w /app

USER 10001:10001

# Default only. Compose overrides it, and production binds 0.0.0.0 behind TLS. Loopback here means
# an image run with no configuration is not reachable, which is the right way for that to fail.
ENV NVSF_BIND_ADDR=127.0.0.1 \
    NVSF_PORT=8000 \
    NVSF_DATA_DIR=/data

EXPOSE 8000

# /api/health/live, not /api/health.
#
# The deep endpoint is the more informative one and it requires a session, so a healthcheck
# calling it gets 403 and Docker restarts a perfectly good container forever. Liveness is the one
# route on the authentication bypass list, put there for this caller.
#
# It also, deliberately, says nothing about the data. A healthcheck should fail only for something
# a restart can fix: if the data volume is unwritable, restarting the container does not help, and
# a restart loop replaces one clear problem with two.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${NVSF_PORT}/api/health/live" || exit 1

# gunicorn.conf.py resolves bind, workers and TLS from the same NVSF_* settings the app reads, so
# there is one configuration surface rather than two.
CMD ["gunicorn", "--config", "backend/gunicorn.conf.py", "app:app"]
