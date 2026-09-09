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
// ValidateView.tsx — paste an export, get a verdict. No model in this path.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// The most useful page in the contract section: a team finds out they are wrong before another
// team depends on their output. Conformance is decidable, so this is deterministic and always
// will be -- a probabilistic answer to a decidable question is strictly worse than a
// deterministic one.
import Box from "@mui/material/Box";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import { Banner, Button, Tag, Text } from "@nvidia/foundations-react-core";
import { useState } from "react";

import { ErrorBanner, InfoBanner, Page, SectionHeading } from "../components/Feedback";
import { useApi } from "../hooks/useApi";
import { ApiError } from "../lib/apiFetch";
import { getFixture, getIndex, validate, validateRecord } from "../services/contracts";
import type { ValidationResult } from "../types/api";

const PLACEHOLDER = `{
  "nrm_version": "v0.1",
  "resources": [
    {
      "id": "0192f5c1-8a3b-7c4d-9e0f-1a2b3c4d5e6f",
      "resource_type_id": "0192f5c1-8a3b-7c4d-9e0f-000000000001",
      "name": "gpu-01",
      "observation": "observed"
    }
  ]
}`;

export function ValidateView() {
  const index = useApi(getIndex);
  const [text, setText] = useState("");
  const [entity, setEntity] = useState("");
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setError(null);
    setResult(null);

    let payload: unknown;
    try {
      payload = JSON.parse(text);
    } catch (caught) {
      // Parsed here rather than sent as-is so a trailing comma gets a precise local answer
      // instead of a round trip that reports "the body must be JSON".
      setError(
        `That is not valid JSON: ${caught instanceof Error ? caught.message : "parse failed"}`,
      );
      setBusy(false);
      return;
    }

    try {
      setResult(entity ? await validateRecord(entity, payload) : await validate(payload));
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : caught instanceof Error
            ? caught.message
            : "Validation failed",
      );
    } finally {
      setBusy(false);
    }
  };

  const loadExample = async () => {
    setBusy(true);
    try {
      const fixture = await getFixture("nvl72-rack");
      setText(JSON.stringify(fixture, null, 2));
      setEntity("");
      setResult(null);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load the example");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Page>
      <SectionHeading
        title="Validate against NRM"
        detail={
          <>
            Schema conformance plus the three things a schema cannot express: every reference
            resolves, containment has no cycles, and link classes and keys agree with their
            endpoints. NRM{" "}
            <span className="nvsf-code">{index.data?.nrm_version ?? "…"}</span>.
          </>
        }
      />

      <InfoBanner>
        Nothing here is sent to a language model, and nothing is stored. This endpoint is the only
        thing that decides conformance — if it says valid, you are conformant, and no other
        opinion overrides it.
      </InfoBanner>

      <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
        <Box sx={{ display: "flex", gap: 2, mb: 2, flexWrap: "wrap", alignItems: "center" }}>
          <TextField
            label="Mode"
            value={entity}
            onChange={(event) => setEntity(event.target.value)}
            select
            size="small"
            sx={{ minWidth: 260 }}
            helperText={
              entity
                ? "Single record. Reference and cycle checks are impossible in this mode."
                : "Bundle: every check runs."
            }
          >
            <MenuItem value="">A bundle (all checks)</MenuItem>
            {(index.data?.entities ?? []).map((option) => (
              <MenuItem key={option.name} value={option.name}>
                One {option.title} record
              </MenuItem>
            ))}
          </TextField>
          <Button kind="secondary" size="small" onClick={() => void loadExample()} disabled={busy}>
            Load the reference NVL72 rack
          </Button>
        </Box>

        <TextField
          label="Your export"
          placeholder={PLACEHOLDER}
          value={text}
          onChange={(event) => setText(event.target.value)}
          multiline
          minRows={14}
          fullWidth
          slotProps={{ input: { style: { fontFamily: "var(--font-mono)", fontSize: 12.5 } } }}
          disabled={busy}
        />

        <Box sx={{ mt: 2, display: "flex", gap: 1, alignItems: "center" }}>
          <Button kind="primary" color="brand" onClick={() => void run()} disabled={busy || !text.trim()}>
            {busy ? "Checking…" : "Validate"}
          </Button>
          <Text kind="body/regular/xs" style={{ color: "var(--text-color-secondary)" }}>
            Bodies over 16 MB are refused before they are parsed — split by rack or by entity.
          </Text>
        </Box>
      </Paper>

      {error && <ErrorBanner message={error} />}

      {result && <Verdict result={result} />}
    </Page>
  );
}

function Verdict({ result }: { result: ValidationResult }) {
  const counts = Object.entries(result.counts ?? {});

  return (
    <>
      <Box sx={{ mb: 2 }}>
        <Banner status={result.valid ? "success" : "error"}>
          <Text kind="body/bold/sm" style={{ display: "block" }}>
            {result.valid
              ? "Conformant."
              : `${result.problem_count} problem${result.problem_count === 1 ? "" : "s"}.`}
          </Text>
          <Text kind="body/regular/sm">
            {result.valid
              ? "This payload can be handed to any NVIS tool that consumes NRM."
              : "Passing the schema and failing the cross-record rules is the normal outcome of a first attempt — start at the top."}
          </Text>
        </Banner>
      </Box>

      {counts.length > 0 && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", alignItems: "center" }}>
            <Text kind="body/regular/xs" style={{ color: "var(--text-color-secondary)" }}>
              checked
            </Text>
            {counts.map(([collection, n]) => (
              <Tag key={collection} color="gray" kind="outline" readOnly density="compact">
                {n} {collection}
              </Tag>
            ))}
          </Box>
        </Paper>
      )}

      {/* What this mode could NOT check. A "valid" that quietly skipped the reference checks is
          the most misleading answer this endpoint could give, so the omission is stated. */}
      {result.not_checked?.length ? (
        <Box sx={{ mb: 2 }}>
          <Banner status="warning" kind="inline">
            Not checked: {result.not_checked.join("; ")}
          </Banner>
        </Box>
      ) : null}

      {result.problems.length > 0 && (
        <Paper variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 280 }}>Where</TableCell>
                <TableCell>Problem</TableCell>
                <TableCell sx={{ width: 220 }}>Rule</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {result.problems.map((problem, index) => (
                <TableRow key={index} hover>
                  {/* A JSON Pointer, so the reader can walk straight to the record rather than
                      searching the document for the message. */}
                  <TableCell sx={{ verticalAlign: "top" }}>
                    <span className="nvsf-code">{problem.pointer || "(root)"}</span>
                  </TableCell>
                  <TableCell sx={{ verticalAlign: "top" }}>
                    <Text kind="body/regular/sm">{problem.message}</Text>
                  </TableCell>
                  <TableCell sx={{ verticalAlign: "top" }}>
                    <span className="nvsf-code">{problem.rule}</span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {result.truncated && (
            <Box sx={{ p: 2 }}>
              <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
                The list is truncated. One systematic mistake produces one problem per record, so
                fixing the first few usually clears most of what is left.
              </Text>
            </Box>
          )}
        </Paper>
      )}
    </>
  );
}
