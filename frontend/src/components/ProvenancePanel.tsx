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
// ProvenancePanel.tsx — which model said what, from which evidence, at what cost.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// Loaded on demand rather than with the page. It sits behind its own permission
// (assessment:provenance, OVA and above) because a raw model response can quote the assessed
// repository, which is a wider grant than reading the conclusions -- and it is large.
//
// This panel is what makes an AI-first tool auditable. A conclusion whose model id, prompt
// version and evidence hash are all recorded can be argued with; one without them can only be
// believed or disbelieved.
import Box from "@mui/material/Box";
import Collapse from "@mui/material/Collapse";
import Paper from "@mui/material/Paper";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tooltip from "@mui/material/Tooltip";
import { Button, Tag, Text } from "@nvidia/foundations-react-core";
import { Fragment, useCallback, useState } from "react";

import { useApi } from "../hooks/useApi";
import { count, when } from "../lib/format";
import { getProvenance } from "../services/factory";
import { ErrorBanner, Loading, SectionHeading } from "./Feedback";

export function ProvenancePanel({ assessmentId }: { assessmentId: string }) {
  const [open, setOpen] = useState(false);

  return (
    <Box sx={{ mb: 4 }}>
      <SectionHeading
        title="Provenance"
        detail="Every model call this run made: which model, which prompt version, which evidence, and what it cost."
        action={
          <Button kind="secondary" size="small" onClick={() => setOpen((value) => !value)}>
            {open ? "Hide" : "Show"}
          </Button>
        }
      />
      {open && <ProvenanceBody assessmentId={assessmentId} />}
    </Box>
  );
}

function ProvenanceBody({ assessmentId }: { assessmentId: string }) {
  const loader = useCallback(
    (signal: AbortSignal) => getProvenance(assessmentId, signal),
    [assessmentId],
  );
  const { data, loading, error } = useApi(loader, [assessmentId]);
  const [expanded, setExpanded] = useState<string | null>(null);

  if (loading && !data) return <Loading rows={4} label="Loading provenance" />;
  if (error) return <ErrorBanner message={error} />;
  if (!data) return null;

  const { llm_calls: calls, token_usage: usage, assessment } = data;

  return (
    <>
      <Paper variant="outlined" sx={{ p: 2.5, mb: 2 }}>
        <Box sx={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
          <Metric label="Model calls" value={count(usage.calls)} />
          <Metric label="Prompt tokens" value={count(usage.prompt_tokens)} />
          <Metric label="Completion tokens" value={count(usage.completion_tokens)} />
          {/* The evidence hash is how two runs are compared honestly: same hash means the same
              input, so any difference in conclusions is the model, not the repository. */}
          <Metric
            label="Evidence hash"
            value={assessment.evidence_hash ? assessment.evidence_hash.slice(0, 12) : "—"}
            help={assessment.evidence_hash ?? undefined}
          />
          <Metric label="Baseline" value={assessment.standards_version ?? "—"} />
        </Box>
      </Paper>

      <Paper variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Pass</TableCell>
              <TableCell>Model</TableCell>
              <TableCell>Prompt</TableCell>
              <TableCell>Temp</TableCell>
              <TableCell>Tokens</TableCell>
              <TableCell>Took</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>When</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {calls.map((call) => {
              const at = when(call.created_at);
              return (
                <Fragment key={call.id}>
                  <TableRow
                    hover
                    sx={{ cursor: call.raw_response ? "pointer" : "default" }}
                    onClick={() =>
                      setExpanded((current) => (current === call.id ? null : call.id))
                    }
                  >
                    <TableCell>{call.pass_name}</TableCell>
                    <TableCell>
                      <span className="nvsf-code">{call.model}</span>
                    </TableCell>
                    <TableCell>
                      <span className="nvsf-code">{call.prompt_version}</span>
                    </TableCell>
                    <TableCell>{call.temperature}</TableCell>
                    <TableCell>
                      {count(call.prompt_tokens)} / {count(call.completion_tokens)}
                    </TableCell>
                    <TableCell>{call.duration_ms ? `${call.duration_ms} ms` : "—"}</TableCell>
                    <TableCell>
                      <Tag
                        color={call.status === "ok" ? "green" : "red"}
                        kind="solid"
                        readOnly
                        density="compact"
                      >
                        {call.status}
                      </Tag>
                    </TableCell>
                    <TableCell>
                      <Tooltip title={at.absolute}>
                        <span>{at.relative}</span>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                  {/* Failed calls are in this table too. A run that succeeded on its third attempt
                      is a different thing from one that succeeded first time, and only the record
                      shows which happened. */}
                  <TableRow>
                    <TableCell colSpan={8} sx={{ py: 0, border: 0 }}>
                      <Collapse in={expanded === call.id}>
                        <Box sx={{ py: 2 }}>
                          {call.error && (
                            <Text
                              kind="body/regular/md"
                              style={{ display: "block", marginBottom: 8 }}
                            >
                              {call.error}
                            </Text>
                          )}
                          {call.raw_response ? (
                            <Box
                              sx={{
                                bgcolor: "action.hover",
                                p: 2,
                                borderRadius: 1,
                                maxHeight: 400,
                                overflow: "auto",
                              }}
                            >
                              <span className="nvsf-code">{call.raw_response}</span>
                            </Box>
                          ) : (
                            <Text
                              kind="body/regular/md"
                              style={{ color: "var(--text-color-secondary)" }}
                            >
                              No raw response recorded for this call.
                            </Text>
                          )}
                        </Box>
                      </Collapse>
                    </TableCell>
                  </TableRow>
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      </Paper>
    </>
  );
}

function Metric({ label, value, help }: { label: string; value: string; help?: string }) {
  const body = (
    <Box>
      <Text
        kind="body/regular/sm"
        style={{ color: "var(--text-color-secondary)", display: "block" }}
      >
        {label}
      </Text>
      <Text kind="body/bold/md">
        <span className="nvsf-code">{value}</span>
      </Text>
    </Box>
  );
  return help ? <Tooltip title={help}>{body}</Tooltip> : body;
}
