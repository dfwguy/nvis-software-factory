# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Mint and derive NRM identities.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Two kinds of identity, for two different jobs.

**Minted** (``new_id``) is a UUIDv7 primary key: opaque, time-ordered, and never derived from
anything about the thing it names. This is what solves the objection to NetBox-style integer keys
without inventing an identity scheme -- a resource can be renamed, re-serialized, moved between
racks or replaced under warranty, and its key survives all of it.

**Derived** (``link_key``) is content-addressable, and exists for exactly one reason: an expected
link read from a P2P cabling file and an observed link discovered by ibnetdiscover must produce the
SAME key. That turns plan-versus-reality into a set difference. With minted link IDs it would be a
matching heuristic against two lists of a few thousand entries, and heuristics there produce
false miscable reports, which cost more trust than they save time.
"""

from __future__ import annotations

import os
import re
import time
import uuid

#: Characters that would make a link key ambiguous. ``:`` separates the two endpoint terms and
#: ``_`` separates resource from port, so neither may appear inside a component.
_UNSAFE = re.compile(r"[:_\s]+")


def new_id() -> str:
    """A fresh UUIDv7 as a lowercase hyphenated string.

    Hand-built rather than taken from ``uuid.uuid7``, which does not exist before Python 3.14. The
    layout is RFC 9562: 48 bits of Unix milliseconds, version 7, 74 bits of randomness. Being
    time-ordered matters more here than it looks -- these are B-tree primary keys in SQLite, and
    random v4 keys scatter inserts across the whole index, which for a bulk rack import is the
    difference between one page write and thousands.
    """
    stamp = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    payload = bytearray(os.urandom(16))
    payload[0:6] = stamp.to_bytes(6, "big")
    payload[6] = 0x70 | (payload[6] & 0x0F)          # version 7
    payload[8] = 0x80 | (payload[8] & 0x3F)          # RFC 9562 variant
    return str(uuid.UUID(bytes=bytes(payload)))


def _term(resource: str, port: str) -> str:
    """One endpoint of a link key, as ``<resource>_<port>``.

    Case is folded and separator runs are collapsed to ``-`` because the two sources being compared
    disagree cosmetically about the same hardware: a cabling spreadsheet says ``Rack01 / OSFP 1``
    and ibnetdiscover says ``rack01:OSFP1``. Normalizing here is what makes them collide. It is
    deliberately the ONLY place in this contract where a value is normalized -- identifiers are
    kept verbatim, because there the value's job is to match a source system exactly.
    """
    clean_resource = _UNSAFE.sub("-", resource.strip().lower()).strip("-")
    clean_port = _UNSAFE.sub("-", port.strip().lower()).strip("-")
    return f"{clean_resource}_{clean_port}"


def link_key(*, a_resource: str, a_port: str, b_resource: str, b_port: str) -> str:
    """Content-addressable key for a link, per UFM's ``<resource>_<port>:<resource>_<port>``.

    The two terms are sorted lexically, which is the part that makes this work. A cabling file
    lists a link switch-first and a discovery sweep reports it node-first; without sorting, the
    same physical cable yields two different keys and every link in the rack reads as both a
    missing cable and an unexpected one.
    """
    terms = sorted((_term(a_resource, a_port), _term(b_resource, b_port)))
    return f"{terms[0]}:{terms[1]}"


def identifier_match_key(fmt: str, value: str, scope: str | None = None) -> str:
    """A comparable key for one identifier, for reconciliation.

    Matching is case-insensitive on the value because the same GUID arrives upper-cased from one
    tool and lower-cased from another, and a reconciliation that misses on case duplicates every
    record on the second import. ``scope`` participates because a SERIAL is only unique within a
    manufacturer -- two vendors will eventually both ship a part numbered ``1234``.
    """
    return f"{fmt}:{(scope or '').strip().lower()}:{value.strip().lower()}"
