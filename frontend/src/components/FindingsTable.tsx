/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */
// FindingsTable.tsx — findings, grouped by severity, each showing where it came from.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import Box from "@mui/material/Box";
import Collapse from "@mui/material/Collapse";
import Paper from "@mui/material/Paper";
import { Text } from "@nvidia/foundations-react-core";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import { pillarLabel } from "../lib/format";
import { SEVERITY_ORDER, severityColor } from "../lib/severity";
import type { Finding } from "../types/api";
import { OriginTag, SeverityTag } from "./labels";

function FindingRow({ finding }: { finding: Finding }) {
  const [open, setOpen] = useState(finding.severity === "blocker");

  return (
    <Box
      sx={{
        borderLeft: 3,
        borderColor: severityColor(finding.severity),
        pl: 2,
        py: 1.5,
        borderBottom: 1,
        borderBottomColor: "divider",
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        style={{
          all: "unset",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
        }}
      >
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <Text kind="body/bold/sm" style={{ flexGrow: 1, textAlign: "left" }}>
          {finding.title}
        </Text>
        <OriginTag origin={finding.origin} escalatedFrom={finding.escalated_from} />
        <SeverityTag severity={finding.severity} />
      </button>

      <Collapse in={open}>
        <Box sx={{ pt: 1.5, pl: 3, display: "grid", gap: 1.5 }}>
          <Text kind="body/regular/sm">{finding.detail}</Text>

          {/* The citation is what makes a finding checkable. A conclusion with no file:line is a
              conclusion the author has to take on trust, and the point of the deterministic layer
              is that they should not have to. */}
          {finding.file_path && (
            <Box>
              <Text
                kind="body/regular/xs"
                style={{ color: "var(--text-color-secondary)", display: "block" }}
              >
                Where
              </Text>
              <span className="nvsf-code">
                {finding.file_path}
                {finding.line_start ? `:${finding.line_start}` : ""}
                {finding.line_end && finding.line_end !== finding.line_start
                  ? `-${finding.line_end}`
                  : ""}
              </span>
            </Box>
          )}

          {finding.citation && (
            <Box
              sx={{
                bgcolor: "action.hover",
                p: 1.5,
                borderRadius: 1,
                maxHeight: 240,
                overflow: "auto",
              }}
            >
              <span className="nvsf-code">{finding.citation}</span>
            </Box>
          )}

          {finding.remediation && (
            <Box>
              <Text
                kind="body/regular/xs"
                style={{ color: "var(--text-color-secondary)", display: "block" }}
              >
                What to do
              </Text>
              <Text kind="body/regular/sm">{finding.remediation}</Text>
            </Box>
          )}

          <Text kind="body/regular/xs" style={{ color: "var(--text-color-secondary)" }}>
            {pillarLabel(finding.pillar_id)}
            {finding.criterion ? ` · criterion ${finding.criterion}` : ""}
            {finding.detector ? ` · detected by ${finding.detector}` : ""}
          </Text>
        </Box>
      </Collapse>
    </Box>
  );
}

export function FindingsTable({ findings }: { findings: Finding[] }) {
  if (!findings.length) {
    return (
      <Paper variant="outlined" sx={{ p: 3 }}>
        <Text kind="body/regular/sm">
          No findings. That is a real result, not an empty page — the scanners ran and the model
          judged every pillar. Read the per-pillar verdicts above to see what was checked.
        </Text>
      </Paper>
    );
  }

  return (
    <Paper variant="outlined">
      {SEVERITY_ORDER.flatMap((severity) => {
        const group = findings.filter((finding) => finding.severity === severity);
        if (!group.length) return [];
        return [
          <Box key={`h-${severity}`} sx={{ px: 2, pt: 2, pb: 1 }}>
            <SeverityTag severity={severity} count={group.length} />
          </Box>,
          ...group.map((finding) => <FindingRow key={finding.id} finding={finding} />),
        ];
      })}
    </Paper>
  );
}
