# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Durable state. SQLite in WAL mode on a bind-mounted host directory.

Author: Rafael M. Koike & Cursor Agent ("Ada")

This package is the reference implementation of the durability pillar the application enforces on
everyone else, so it is worth stating plainly what it does and does not promise:

* **Survives a process crash.** WAL plus ``synchronous = FULL`` plus explicit transactions.
* **Survives a container restart.** State is on a bind mount, not in the container's writable
  layer and not in a named volume that ``docker volume prune`` can remove.
* **Survives a bad migration.** Each migration runs in a transaction, and applied migrations are
  checksummed so an edited one is refused rather than silently reapplied.
* **Snapshots are verified**, not merely taken -- an unverified backup is a belief.
* **Does NOT survive losing the volume or the host.** Snapshots live on the same volume as the
  live data. That limitation is stated in the deployment guide and in ``backup.health()``, because
  a backup with an unstated blast radius buys false confidence.

Flask-free by design: everything here is importable and testable without an app context.

    from store import repo, migrations, backup
"""

from __future__ import annotations

from . import backup, db, migrations, models, repo

__all__ = ["backup", "db", "migrations", "models", "repo"]
