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
// CrosswalksView.tsx — coverage per system, gaps included.
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
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

import { ErrorBanner, InfoBanner, Loading, Page, SectionHeading } from "../components/Feedback";
import { RoleTag } from "../components/labels";
import { useApi } from "../hooks/useApi";
import { crosswalkPath } from "../routes";
import { getCoverage } from "../services/contracts";

/** What a role means for data flow. The whole reason a crosswalk declares one. */
const ROLE_MEANING: Record<string, string> = {
  source_of_record:
    "Authoritative. Where this system and NRM disagree about an asset, this system is right.",
  discovery: "Reports what the hardware says about itself. Import only.",
  observed_state: "Reports measured reality. Import only, and never a planning input.",
  planning_input: "Describes intent, not reality. Produces expected records.",
  telemetry_join: "Not an inventory source at all — it joins metrics to NRM identity.",
  export_target: "NRM writes to it. It never originates anything.",
};

export function CrosswalksView() {
  const { data, loading, error } = useApi(getCoverage);

  if (loading && !data) return <Page><Loading rows={6} /></Page>;
  if (error) return <Page><ErrorBanner message={error} /></Page>;
  if (!data) return null;

  const systems = Object.entries(data.systems).sort(([a], [b]) => a.localeCompare(b));

  return (
    <Page>
      <SectionHeading
        title="Crosswalks"
        detail={
          <>
            {systems.length} systems mapped against NRM{" "}
            <span className="nvsf-code">{data.nrm_version}</span>. If your tool already speaks one
            of these, map through it rather than inventing a mapping.
          </>
        }
      />

      <InfoBanner>
        Each crosswalk is validated data, not prose: it is checked against both its own schema and
        the NRM schemas at startup, so a mapping that names a field the contract no longer has
        stops this application from booting. That is why the gap counts below can be trusted.
      </InfoBanner>

      <Paper variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>System</TableCell>
              <TableCell>Role</TableCell>
              <TableCell>Entities mapped</TableCell>
              <TableCell align="right">Fields</TableCell>
              <TableCell align="right">Documented gaps</TableCell>
              <TableCell align="right">Unreliable</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {systems.map(([system, coverage]) => {
              const entities = Object.entries(coverage.entities);
              const fields = entities.reduce((sum, [, e]) => sum + e.mapped_fields, 0);
              const gaps = entities.reduce((sum, [, e]) => sum + e.documented_gaps, 0);
              const unreliable = entities.reduce((sum, [, e]) => sum + e.unreliable_fields, 0);

              return (
                <TableRow key={system} hover>
                  <TableCell>
                    <Link to={crosswalkPath(system)}>
                      <span className="nvsf-code">{system}</span>
                    </Link>
                    {coverage.system_version && (
                      <Text
                        kind="body/regular/sm"
                        style={{ color: "var(--text-color-secondary)", display: "block" }}
                      >
                        {coverage.system_version}
                      </Text>
                    )}
                  </TableCell>
                  <TableCell>
                    <Tooltip title={ROLE_MEANING[coverage.role] ?? coverage.role}>
                      <span>
                        <RoleTag role={coverage.role} />
                      </span>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap" }}>
                      {entities.map(([name, entity]) => (
                        <Tooltip
                          key={name}
                          title={`${entity.direction} — ${entity.mapped_fields} fields`}
                        >
                          <span>
                            <Tag color="gray" kind="outline" readOnly density="compact">
                              {name}
                            </Tag>
                          </span>
                        </Tooltip>
                      ))}
                    </Box>
                    {/* Which entities a system does NOT map, stated. A crosswalk that covers four
                        of seven entities is useful; one that silently implies it covers all seven
                        is how an integration discovers a gap in production. */}
                    {coverage.missing_entities.length > 0 && (
                      <Text
                        kind="body/regular/sm"
                        style={{ color: "var(--text-color-secondary)", display: "block", marginTop: 4 }}
                      >
                        not mapped: {coverage.missing_entities.join(", ")}
                      </Text>
                    )}
                  </TableCell>
                  <TableCell align="right">{fields}</TableCell>
                  <TableCell align="right">
                    <Tooltip title="NRM fields this system cannot carry, each with a stated reason.">
                      <span>{gaps}</span>
                    </Tooltip>
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title="Mappings that work but should not be trusted blindly — a free-text field parsed for structure, for instance.">
                      <span>{unreliable || "—"}</span>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <Link to={crosswalkPath(system)}>
                      <ChevronRight size={16} />
                    </Link>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Paper>
    </Page>
  );
}
