# SPDX-License-Identifier: LicenseRef-NVIDIA-Internal
# Author: Rafael M. Koike & Cursor Agent ("Ada")
"""NVIS Resource Model: schema loading, validation, crosswalk, and identity.

The contract front of the Software Factory. Where `factory/` judges other people's software,
this package publishes the data contract those teams build against.

The division of labour with the LLM is the opposite of the factory's, and deliberately so. In
`factory/`, the model reasons and deterministic scanners constrain it. Here, the model only ever
*proposes* -- a crosswalk mapping from a team's export to NRM -- and `jsonschema` decides whether
the proposal is correct. The model never adjudicates conformance, because conformance is decidable
and a probabilistic answer to a decidable question is strictly worse than a deterministic one.
"""

from __future__ import annotations

from contracts.loader import (
    ContractError,
    UnknownEntity,
    UnknownVersion,
    entity_names,
    load_schema,
    schema_path,
    versions,
)

__all__ = [
    "ContractError",
    "UnknownEntity",
    "UnknownVersion",
    "entity_names",
    "load_schema",
    "schema_path",
    "versions",
]
