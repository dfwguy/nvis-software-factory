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
// EntityView.tsx — one entity's fields, rendered from its schema.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// Rendered from the schema rather than from a hand-written page. Every field's `description` in
// the schema carries the reasoning for that field, which was written to be read -- so this page
// is a view onto the contract, and cannot describe a field the contract does not have.
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import { Tag, Text } from "@nvidia/foundations-react-core";
import { ChevronLeft } from "lucide-react";
import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";

import { CopyButton } from "../components/CopyButton";
import { ErrorBanner, Loading, Page, SectionHeading } from "../components/Feedback";
import { Markdown } from "../components/Markdown";
import { useApi } from "../hooks/useApi";
import { CONTRACT_PATH } from "../routes";
import { getIndex, getSchema } from "../services/contracts";
import type { JsonSchemaProperty } from "../types/api";

/** A property's type, as a reader would say it. */
function typeOf(property: JsonSchemaProperty): string {
  if (property.$ref) {
    // `#/$defs/uuid` and `common.schema.json#/$defs/identifier` both reduce to their last
    // segment, which is the name a reader recognizes.
    return property.$ref.split("/").pop() ?? "reference";
  }
  if (property.enum) return "enum";
  if (property.type === "array") {
    const items = property.items;
    const inner = items ? typeOf(items) : "any";
    return `${inner}[]`;
  }
  return Array.isArray(property.type) ? property.type.join(" | ") : (property.type ?? "any");
}

export function EntityView() {
  const { entity = "" } = useParams<{ entity: string }>();
  const index = useApi(getIndex);
  const version = index.data?.nrm_version;

  const loader = useCallback(
    (signal: AbortSignal) =>
      version ? getSchema(entity, version, signal) : Promise.reject(new Error("no version")),
    [entity, version],
  );
  const { data, loading, error } = useApi(loader, [entity, version]);

  if (!version || (loading && !data)) return <Page><Loading rows={10} /></Page>;
  if (error) {
    return (
      <Page>
        <ErrorBanner message={error} />
        <Link to={CONTRACT_PATH}>Back to the contract</Link>
      </Page>
    );
  }
  if (!data) return null;

  const required = new Set(data.required ?? []);
  const properties = Object.entries(data.properties ?? {});
  const schemaFile = `${entity}.schema.json`;

  return (
    <Page>
      <Box sx={{ mb: 2 }}>
        <Link to={CONTRACT_PATH} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <ChevronLeft size={14} />
          <Text kind="body/regular/md">All entities</Text>
        </Link>
      </Box>

      <SectionHeading
        title={data.title ?? entity}
        detail={
          <>
            <span className="nvsf-code">{schemaFile}</span> · NRM{" "}
            <span className="nvsf-code">{version}</span> · {properties.length} fields,{" "}
            {required.size} required
            {data.additionalProperties === false
              ? " · unknown fields are rejected"
              : ""}
          </>
        }
        action={
          <Box sx={{ display: "flex", gap: 1 }}>
            <CopyButton text={JSON.stringify(data, null, 2)} label="Copy schema" />
          </Box>
        }
      />

      {data.description && (
        <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
          <Markdown source={data.description} />
        </Paper>
      )}

      <Paper variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ width: 200 }}>Field</TableCell>
              <TableCell sx={{ width: 160 }}>Type</TableCell>
              <TableCell>What it is for</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {properties.map(([name, property]) => (
              <TableRow key={name} hover>
                <TableCell sx={{ verticalAlign: "top" }}>
                  <Box sx={{ display: "flex", gap: 1, alignItems: "baseline", flexWrap: "wrap" }}>
                    <span className="nvsf-code">{name}</span>
                    {required.has(name) && (
                      <Tag color="red" kind="outline" readOnly density="compact">
                        required
                      </Tag>
                    )}
                  </Box>
                </TableCell>
                <TableCell sx={{ verticalAlign: "top" }}>
                  <span className="nvsf-code">{typeOf(property)}</span>
                  {property.format && (
                    <Text
                      kind="body/regular/sm"
                      style={{ color: "var(--text-color-secondary)", display: "block" }}
                    >
                      {property.format}
                    </Text>
                  )}
                  {property.const !== undefined && (
                    <Text
                      kind="body/regular/sm"
                      style={{ color: "var(--text-color-secondary)", display: "block" }}
                    >
                      always {JSON.stringify(property.const)}
                    </Text>
                  )}
                </TableCell>
                <TableCell sx={{ verticalAlign: "top" }}>
                  {/* The description is the field's rationale, written in prose. Rendered as
                      Markdown because that is how it is written in the schema files, and
                      flattening it to one line loses the paragraph that explains the trap. */}
                  {property.description ? (
                    <Markdown source={property.description} />
                  ) : (
                    <Text kind="body/regular/md" style={{ color: "var(--text-color-secondary)" }}>
                      No description in the schema. That is a gap worth reporting.
                    </Text>
                  )}
                  {property.enum && (
                    <Box sx={{ mt: 1, display: "flex", gap: 0.5, flexWrap: "wrap" }}>
                      {property.enum.map((value) => (
                        <Tag key={value} color="gray" kind="outline" readOnly density="compact">
                          {value}
                        </Tag>
                      ))}
                    </Box>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
    </Page>
  );
}
