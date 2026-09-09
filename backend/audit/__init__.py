# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Audit trail: an append-only JSONL sink and the request chokepoint that feeds it.

Author: Rafael M. Koike & Cursor Agent ("Ada")

    from audit import record

    record(actor=principal.subject, action="assessment:create", outcome="ok",
           resource=assessment.id, detail={"repository": repo.canonical_url})

HTTP requests are recorded automatically by ``request_hook``. Call :func:`record` directly only
for state changes that do not arrive over HTTP -- the assessment worker's transitions, scheduled
snapshots.
"""

from __future__ import annotations

from . import request_hook, sink
from .sink import available_days, build_event, emit, read_day, record

__all__ = [
    "available_days",
    "build_event",
    "emit",
    "read_day",
    "record",
    "request_hook",
    "sink",
]
