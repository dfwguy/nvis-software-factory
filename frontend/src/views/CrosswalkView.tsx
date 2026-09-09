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
// CrosswalkView.tsx — one system's mapping, field by field, gaps and all.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tooltip from "@mui/material/Tooltip";
import { Tag, Text } from "@nvidia/foundations-react-core";
import { ChevronLeft } from "lucide-react";
import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";

import { CopyButton } from "../components/CopyButton";
import { ErrorBanner, Loading, Page, SectionHeading } from "../components/Feedback";
import { RoleTag } from "../components/labels";
import { useApi } from "../hooks/useApi";
import { CONTRACT_PATH, entityPath } from "../routes";
import { getCrosswalk } from "../services/contracts";

const DIRECTION_HELP: Record<string, string> = {
  import: "Data flows from this system into NRM.",
  export: "NRM writes this field out to the system.",
  both: "Either direction; the join key keeps the two reconciled.",
};

export function CrosswalkView() {
  const { system = "" } = useParams<{ system: string }>();
  const loader = useCallback((signal: AbortSignal) => getCrosswalk(system, signal), [system]);
  const { data, loading, error } = useApi(loader, [system]);

  if (loading && !data) return <Page><Loading rows={10} /></Page>;
  if (error) {
    return (
      <Page>
        <ErrorBanner message={error} />
        <Link to={`${CONTRACT_PATH}/crosswalk`}>Back to crosswalks</Link>
      </Page>
    );
  }
  if (!data) return null;

  return (
    <Page>
      <Box sx={{ mb: 2 }}>
        <Link
          to={`${CONTRACT_PATH}/crosswalk`}
          style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
        >
          <ChevronLeft size={14} />
          <Text kind="body/regular/sm">All crosswalks</Text>
        </Link>
      </Box>

      <SectionHeading
        title={data.system}
        detail={
          <>
            <RoleTag role={data.role} /> · crosswalk{" "}
            <span className="nvsf-code">{data.crosswalk_version}</span> against NRM{" "}
            <span className="nvsf-code">{data.nrm_version}</span>
            {data.system_version ? ` · ${data.system_version}` : ""}
          </>
        }
        action={<CopyButton text={JSON.stringify(data, null, 2)} label="Copy as JSON" />}
      />

      {/* Authority first. It is the thing that settles arguments: when two systems disagree about
          the same asset, this sentence says which one to believe. */}
      {data.authority && (
        <Paper variant="outlined" sx={{ p: 2.5, mb: 3 }}>
          <Text kind="body/bold/sm" style={{ display: "block", marginBottom: 4 }}>
            Authority
          </Text>
          <Text kind="body/regular/sm">{data.authority}</Text>
        </Paper>
      )}

      {data.join && (
        <Paper variant="outlined" sx={{ p: 2.5, mb: 3 }}>
          <Text kind="body/bold/sm" style={{ display: "block", marginBottom: 4 }}>
            How records are matched
          </Text>
          <Text kind="body/regular/sm" style={{ display: "block" }}>
            <span className="nvsf-code">{data.join.nrm_field}</span> ↔{" "}
            <span className="nvsf-code">{data.join.system_field}</span>
          </Text>
          {data.join.note && (
            <Text
              kind="body/regular/sm"
              style={{ color: "var(--text-color-secondary)", display: "block", marginTop: 4 }}
            >
              {data.join.note}
            </Text>
          )}
        </Paper>
      )}

      {data.entities.map((entity) => (
        <Box key={entity.nrm_entity} sx={{ mb: 4 }}>
          <SectionHeading
            title={
              <>
                <Link to={entityPath(entity.nrm_entity)}>{entity.nrm_entity}</Link>
                {" ↔ "}
                <span className="nvsf-code">{entity.system_model}</span>
              </>
            }
            detail={
              <>
                <Tooltip title={DIRECTION_HELP[entity.direction] ?? entity.direction}>
                  <span>
                    <Tag color="gray" kind="outline" readOnly density="compact">
                      {entity.direction}
                    </Tag>
                  </span>
                </Tooltip>{" "}
                {entity.note}
              </>
            }
          />

          <Paper variant="outlined" sx={{ mb: 2 }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>NRM field</TableCell>
                  <TableCell>{data.system} field</TableCell>
                  <TableCell>Direction</TableCell>
                  <TableCell>Notes</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {entity.fields.map((field) => (
                  <TableRow key={field.nrm} hover>
                    <TableCell>
                      <span className="nvsf-code">{field.nrm}</span>
                    </TableCell>
                    <TableCell>
                      <span className="nvsf-code">{field.system ?? "—"}</span>
                      {field.transform && (
                        <Text
                          kind="body/regular/xs"
                          style={{ color: "var(--text-color-secondary)", display: "block" }}
                        >
                          via {field.transform}
                          {data.transforms?.[field.transform]
                            ? ` — ${data.transforms[field.transform]}`
                            : ""}
                        </Text>
                      )}
                    </TableCell>
                    <TableCell>{field.direction ?? entity.direction}</TableCell>
                    <TableCell>
                      {/* An unreliable mapping is labelled rather than dropped. Dropping it would
                          lose a usable-with-care path; presenting it unlabelled would let someone
                          build a reconciliation on a parsed free-text field. */}
                      {field.unreliable && (
                        <Tooltip title="Works, but do not trust it blindly — typically structure parsed out of a free-text field.">
                          <span>
                            <Tag color="yellow" kind="outline" readOnly density="compact">
                              unreliable
                            </Tag>
                          </span>
                        </Tooltip>
                      )}{" "}
                      <Text kind="body/regular/sm">{field.note}</Text>
                      {field.values && (
                        <Box sx={{ mt: 0.5 }}>
                          {Object.entries(field.values).map(([from, to]) => (
                            <Text
                              key={from}
                              kind="body/regular/xs"
                              style={{ display: "block", color: "var(--text-color-secondary)" }}
                            >
                              <span className="nvsf-code">{from}</span> →{" "}
                              <span className="nvsf-code">{to}</span>
                            </Text>
                          ))}
                        </Box>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>

          {/* The section a reader should check before relying on a mapping. Every crosswalk is
              required to declare it, with a reason per field -- a mapping that silently drops a
              field is how two systems end up disagreeing with nobody noticing. */}
          {entity.unmapped_nrm && entity.unmapped_nrm.length > 0 && (
            <Paper variant="outlined" sx={{ p: 2.5 }}>
              <Text kind="body/bold/sm" style={{ display: "block", marginBottom: 8 }}>
                What {data.system} cannot carry
              </Text>
              <Box sx={{ display: "grid", gap: 1 }}>
                {entity.unmapped_nrm.map((gap) => (
                  <Box key={gap.field}>
                    <span className="nvsf-code">{gap.field}</span>
                    <Text
                      kind="body/regular/sm"
                      style={{ color: "var(--text-color-secondary)", display: "block" }}
                    >
                      {gap.reason}
                    </Text>
                  </Box>
                ))}
              </Box>
            </Paper>
          )}
        </Box>
      ))}

      {data.recommended_labels && (
        <Paper variant="outlined" sx={{ p: 2.5 }}>
          <Text kind="body/bold/sm" style={{ display: "block", marginBottom: 8 }}>
            Recommended labels
          </Text>
          {Object.entries(data.recommended_labels).map(([label, meaning]) => (
            <Box key={label} sx={{ mb: 1 }}>
              <span className="nvsf-code">{label}</span>
              <Text
                kind="body/regular/sm"
                style={{ color: "var(--text-color-secondary)", display: "block" }}
              >
                {meaning}
              </Text>
            </Box>
          ))}
        </Paper>
      )}
    </Page>
  );
}
