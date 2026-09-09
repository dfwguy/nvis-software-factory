# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The assessment engine.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The pipeline, in order:

    acquire  -> sandboxed shallow clone; repository code is never executed
    scanners -> deterministic facts with file:line citations
    redact   -> secret candidates replaced by shape descriptions, before serialization
    evidence -> one bounded document; the only thing the model ever sees
    passes   -> required LLM reasoning, persisted per pass so an outage resumes
    ratchet  -> merge scanner facts with model judgement; escalation only
    render   -> the Markdown bundle an SA feeds to their own agent

Flask-free: every module here is importable and testable without an app context. If something in
here needs ``request`` or ``g``, the dependency belongs in the blueprint that calls it.

Read ``.cursor/rules/ai-first-boundaries.mdc`` before changing anything in this package. The
division of authority between the scanners and the model is the load-bearing idea, and it is easy
to erode one convenience at a time.
"""

from __future__ import annotations

from . import llm, prompts, standards

__all__ = ["llm", "prompts", "standards"]
