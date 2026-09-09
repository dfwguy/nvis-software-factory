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
// MappingAssistantView.tsx — the model proposes a crosswalk; the schema adjudicates it.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// The division of labour here is the inverse of the factory's, and the page is laid out to make
// that obvious. In an assessment the model reasons and scanners constrain it. Here the model only
// guesses which of your fields means which NRM field -- a matching problem a model is genuinely
// good at and a rule set is not -- and then its worked example is run through the validator
// before anyone sees it.
//
// So the verdict is shown ABOVE the mapping, and the model's own confidence is shown next to a
// label saying it carries no weight. A high-confidence proposal that failed validation is the
// single most useful output this page produces, and burying the verdict below the table would
// invite exactly the mistake the adjudication exists to prevent.
import Box from "@mui/material/Box";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import { Banner, Button, Tag, Text } from "@nvidia/foundations-react-core";
import { Link } from "react-router-dom";
import { useState } from "react";

import { CopyButton } from "../components/CopyButton";
import { ErrorBanner, InfoBanner, Page, SectionHeading, WarningBanner } from "../components/Feedback";
import { useApi } from "../hooks/useApi";
import { ApiError } from "../lib/apiFetch";
import { CONTRACT_PATH } from "../routes";
import { getCoverage, getIndex, proposeMapping } from "../services/contracts";
import type { MappingProposal } from "../types/api";

const PLACEHOLDER = `{
  "hostname": "dgx-042",
  "serial_no": "1234ABCD",
  "chassis_model": "NVL72-COMPUTE-TRAY",
  "rack": "R14",
  "u_position": 22,
  "state": "provisioned"
}`;

export function MappingAssistantView() {
  const index = useApi(getIndex);
  const coverage = useApi(getCoverage);

  const entityOptions = index.data?.entities ?? [];

  const [sample, setSample] = useState("");
  const [entity, setEntity] = useState("resource");
  const [system, setSystem] = useState("");
  const [description, setDescription] = useState("");
  const [result, setResult] = useState<MappingProposal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // An existing crosswalk is reviewed; a fresh proposal is not. Saying so before the user spends
  // a model call is cheaper than saying it after.
  const existing = system.trim().toLowerCase();
  const alreadyMapped = Object.keys(coverage.data?.systems ?? {}).find(
    (known) => known === existing || existing.includes(known),
  );

  const run = async () => {
    setBusy(true);
    setError(null);
    setUnavailable(null);
    setResult(null);

    let parsed: unknown;
    try {
      parsed = JSON.parse(sample);
    } catch {
      setError("The sample must be valid JSON — one representative record from your export.");
      setBusy(false);
      return;
    }

    try {
      setResult(
        await proposeMapping({
          sample: parsed,
          entity,
          system: system.trim() || undefined,
          description: description.trim() || undefined,
        }),
      );
    } catch (caught) {
      if (caught instanceof ApiError && caught.reason === "llm-unavailable") {
        setUnavailable(caught.message);
      } else {
        setError(caught instanceof Error ? caught.message : "Could not propose a mapping");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Page>
      <SectionHeading
        title="Mapping assistant"
        detail="Paste one record from your tool's export. The model proposes a mapping onto NRM and writes a worked example; the validator then decides whether that example is conformant."
      />

      <InfoBanner>
        This is the one place a model is allowed near the contract, and it never gets the last
        word. Read the verdict, not the confidence.
      </InfoBanner>

      {alreadyMapped && (
        <WarningBanner>
          There is already a reviewed crosswalk for{" "}
          <Link to={`${CONTRACT_PATH}/crosswalk/${alreadyMapped}`}>{alreadyMapped}</Link>. Map
          through that one — it has been checked against the schemas, and this proposal will not
          have been.
        </WarningBanner>
      )}

      <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
        <Box sx={{ display: "flex", gap: 2, mb: 2, flexWrap: "wrap" }}>
          <TextField
            label="Target entity"
            /* Blank until the entity list has loaded. The default is a real entity name, so
               rendering it against an empty option list makes MUI hold a value it cannot show --
               the field looks empty while the form submits something the user never saw. */
            value={entityOptions.length > 0 ? entity : ""}
            onChange={(event) => setEntity(event.target.value)}
            select
            size="small"
            sx={{ minWidth: 220 }}
            disabled={busy || entityOptions.length === 0}
          >
            {entityOptions.map((option) => (
              <MenuItem key={option.name} value={option.name}>
                {option.title}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Your tool or system"
            placeholder="rack-status exporter"
            value={system}
            onChange={(event) => setSystem(event.target.value)}
            size="small"
            sx={{ minWidth: 240 }}
            disabled={busy}
          />
          <TextField
            label="What the record represents"
            placeholder="One compute tray as our inventory script emits it"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            size="small"
            sx={{ flexGrow: 1, minWidth: 280 }}
            disabled={busy}
          />
        </Box>

        <TextField
          label="One record from your export"
          placeholder={PLACEHOLDER}
          value={sample}
          onChange={(event) => setSample(event.target.value)}
          multiline
          minRows={10}
          fullWidth
          slotProps={{ input: { style: { fontFamily: "var(--font-mono)", fontSize: 12.5 } } }}
          disabled={busy}
          helperText="One record, not the whole export. The model reasons better about one, and the sample is truncated server-side anyway."
        />

        <Box sx={{ mt: 2 }}>
          <Button kind="primary" color="brand" onClick={() => void run()} disabled={busy || !sample.trim()}>
            {busy ? "Proposing…" : "Propose a mapping"}
          </Button>
        </Box>
      </Paper>

      {unavailable && (
        <Box sx={{ mb: 2 }}>
          <Banner status="warning">
            <Text kind="body/bold/md" style={{ display: "block" }}>
              The reasoning endpoint is unreachable.
            </Text>
            <Text kind="body/regular/md">
              {unavailable} There is deliberately no keyword-matching fallback: it would produce a
              plausible-looking crosswalk with no reasoning behind it, and you would have no way to
              tell the difference. The{" "}
              <Link to={`${CONTRACT_PATH}/validate`}>validator</Link> still works — it never
              needed a model.
            </Text>
          </Banner>
        </Box>
      )}

      {error && <ErrorBanner message={error} />}

      {result && <Proposal result={result} />}
    </Page>
  );
}

function Proposal({ result }: { result: MappingProposal }) {
  const verdict = result.adjudication;
  const unmapped = normalize(result.unmapped_source_fields);
  const unfilled = normalize(result.unfilled_required_fields);

  return (
    <>
      <Box sx={{ mb: 2 }}>
        <Banner status={verdict.valid ? "success" : "error"}>
          <Text kind="body/bold/md" style={{ display: "block" }}>
            {verdict.valid
              ? `The worked example is conformant as a ${result.entity} record.`
              : `The worked example is NOT conformant: ${verdict.problem_count} problem${
                  verdict.problem_count === 1 ? "" : "s"
                }.`}
          </Text>
          <Text kind="body/regular/md">
            This is the verdict that counts. It comes from the same validator any NVIS tool would
            run against your output.
          </Text>
        </Banner>
      </Box>

      {verdict.problems.length > 0 && (
        <Paper variant="outlined" sx={{ mb: 3 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 240 }}>Where</TableCell>
                <TableCell>Problem</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {verdict.problems.map((problem, index) => (
                <TableRow key={index}>
                  <TableCell sx={{ verticalAlign: "top" }}>
                    <span className="nvsf-code">{problem.pointer || "(root)"}</span>
                  </TableCell>
                  <TableCell>
                    <Text kind="body/regular/md">{problem.message}</Text>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      <Paper variant="outlined" sx={{ p: 2.5, mb: 3 }}>
        <Box sx={{ display: "flex", gap: 2, alignItems: "center", flexWrap: "wrap" }}>
          <Tooltip title="The model's own opinion of its mapping. It has no bearing on whether the record is valid, and is shown only so a mismatch between it and the verdict above is visible.">
            <span>
              <Tag color="gray" kind="outline" readOnly density="compact">
                model confidence: {result.model_confidence ?? "not stated"}
              </Tag>
            </span>
          </Tooltip>
          <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
            {result.provenance.model} · prompt {result.provenance.prompt_version} · temperature{" "}
            {result.provenance.temperature}
          </Text>
        </Box>
        {result.model_confidence_reason && (
          <Text
            kind="body/regular/md"
            style={{ color: "var(--text-color-secondary)", display: "block", marginTop: 8 }}
          >
            {result.model_confidence_reason}
          </Text>
        )}
      </Paper>

      <SectionHeading
        title="Proposed field mapping"
        detail="A starting point for review, not a crosswalk. A reviewed crosswalk lives in the repository and is checked at startup; this is not."
      />
      <Paper variant="outlined" sx={{ mb: 3 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Your field</TableCell>
              <TableCell>NRM field</TableCell>
              <TableCell>Transform</TableCell>
              <TableCell>Why</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {result.field_map.map((mapping, index) => (
              <TableRow key={index} hover>
                <TableCell>
                  <span className="nvsf-code">{mapping.source_field}</span>
                </TableCell>
                <TableCell>
                  <span className="nvsf-code">{mapping.nrm_field}</span>
                </TableCell>
                <TableCell>{mapping.transform ?? "—"}</TableCell>
                <TableCell>
                  <Text kind="body/regular/md">{mapping.reasoning}</Text>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { md: "1fr 1fr" }, mb: 3 }}>
        <Paper variant="outlined" sx={{ p: 2.5 }}>
          <Text kind="body/bold/md" style={{ display: "block", marginBottom: 8 }}>
            Your fields with nowhere to go ({unmapped.length})
          </Text>
          {unmapped.length ? (
            unmapped.map((item, index) => (
              <Text key={index} kind="body/regular/md" style={{ display: "block" }}>
                {item}
              </Text>
            ))
          ) : (
            <Text kind="body/regular/md" style={{ color: "var(--text-color-secondary)" }}>
              Everything in the sample was mapped. Anything the contract does not model has a home
              in <span className="nvsf-code">attributes</span>.
            </Text>
          )}
        </Paper>
        <Paper variant="outlined" sx={{ p: 2.5 }}>
          <Text kind="body/bold/md" style={{ display: "block", marginBottom: 8 }}>
            NRM fields your export cannot fill ({unfilled.length})
          </Text>
          {unfilled.length ? (
            unfilled.map((item, index) => (
              <Text key={index} kind="body/regular/md" style={{ display: "block" }}>
                {item}
              </Text>
            ))
          ) : (
            <Text kind="body/regular/md" style={{ color: "var(--text-color-secondary)" }}>
              Nothing missing.
            </Text>
          )}
        </Paper>
      </Box>

      {result.record && (
        <Paper variant="outlined" sx={{ p: 2.5 }}>
          <Box
            sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}
          >
            <Text kind="body/bold/md">The worked example that was adjudicated</Text>
            <CopyButton text={JSON.stringify(result.record, null, 2)} />
          </Box>
          <Box sx={{ bgcolor: "action.hover", p: 2, borderRadius: 1, maxHeight: 420, overflow: "auto" }}>
            <span className="nvsf-code">{JSON.stringify(result.record, null, 2)}</span>
          </Box>
        </Paper>
      )}
    </>
  );
}

/** The prompt asks for objects but a model sometimes answers with plain strings. Accept both. */
function normalize(entries: { field?: string; why?: string }[] | string[]): string[] {
  return entries.map((entry) =>
    typeof entry === "string" ? entry : [entry.field, entry.why].filter(Boolean).join(" — "),
  );
}
