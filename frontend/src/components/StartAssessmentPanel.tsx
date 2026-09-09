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
// StartAssessmentPanel.tsx — URL in, run started.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// The intake questions are optional and collapsed by default, and that is a considered choice
// rather than laziness. They materially improve the report -- "who depends on this" changes the
// severity of every durability finding -- but a required six-field form in front of the primary
// action is how a tool goes unused. Ask for the URL, offer the context, say what it buys.
import Box from "@mui/material/Box";
import Collapse from "@mui/material/Collapse";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import TextField from "@mui/material/TextField";
import { Button, Text } from "@nvidia/foundations-react-core";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../lib/apiFetch";
import { startAssessment } from "../services/factory";
import { ErrorBanner, WarningBanner } from "./Feedback";

interface Props {
  /** Called with the new assessment id. The caller decides where to go. */
  onStarted: (assessmentId: string) => void;
  /** Prefilled when starting from a repository's own page. */
  repositoryId?: string;
  repositoryLabel?: string;
}

const CRITICALITY = [
  { value: "experiment", label: "An experiment — only I use it" },
  { value: "team-tool", label: "A team tool — my team depends on it" },
  { value: "shared-service", label: "A shared service — other teams depend on it" },
  { value: "customer-facing", label: "Customer-facing — used during a deployment" },
];

export function StartAssessmentPanel({ onStarted, repositoryId, repositoryLabel }: Props) {
  const [url, setUrl] = useState("");
  const [ref, setRef] = useState("");
  const [purpose, setPurpose] = useState("");
  const [criticality, setCriticality] = useState("");
  const [dataHandled, setDataHandled] = useState("");
  const [showContext, setShowContext] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setUnavailable(null);
    try {
      const result = await startAssessment({
        repositoryId,
        url: repositoryId ? undefined : url.trim(),
        ref: ref.trim() || undefined,
        purpose: purpose.trim() || undefined,
        criticality: criticality || undefined,
        data_handled: dataHandled.trim() || undefined,
      });
      onStarted(result.assessment.id);
    } catch (caught) {
      if (caught instanceof ApiError && caught.reason === "llm-unavailable") {
        // Its own state, not the generic error slot. This is not the user's mistake and there is
        // nothing for them to correct: reasoning is a required stage, so the run cannot start
        // until the endpoint is back. Saying so plainly beats a red box next to the URL field.
        setUnavailable(caught.message);
      } else if (caught instanceof ApiError && caught.reason === "already-running") {
        const existing = caught.body.assessment_id;
        setError(
          typeof existing === "string"
            ? `An assessment of this repository is already running. Open it from the ` +
              `Assessments list, or wait for it to finish.`
            : caught.message,
        );
      } else {
        setError(caught instanceof Error ? caught.message : "Could not start the assessment");
      }
    } finally {
      setBusy(false);
    }
  };

  const ready = repositoryId ? true : url.trim().length > 0;

  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Text kind="body/bold/xl" style={{ display: "block", marginBottom: 4 }}>
        {repositoryLabel ? `Assess ${repositoryLabel}` : "Assess a repository"}
      </Text>
      <Text
        kind="body/regular/md"
        style={{ color: "var(--text-color-secondary)", display: "block", marginBottom: 16 }}
      >
        A shallow, read-only clone. Nothing from the repository is executed, and anything
        credential-shaped is replaced with a description of its shape before it reaches the model.
      </Text>

      {unavailable && <WarningBanner>{unavailable}</WarningBanner>}
      {error && <ErrorBanner message={error} />}

      <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap", alignItems: "flex-start" }}>
        {!repositoryId && (
          <TextField
            label="Repository URL"
            placeholder="https://gitlab-master.nvidia.com/nvis/some-tool"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            size="small"
            sx={{ flexGrow: 1, minWidth: 320 }}
            disabled={busy}
          />
        )}
        <TextField
          label="Branch or tag"
          placeholder="default branch"
          value={ref}
          onChange={(event) => setRef(event.target.value)}
          size="small"
          sx={{ width: 180 }}
          disabled={busy}
        />
        <Box sx={{ pt: 0.5 }}>
          <Button kind="primary" color="brand" onClick={submit} disabled={!ready || busy}>
            {busy ? "Starting…" : "Start assessment"}
          </Button>
        </Box>
      </Box>

      <Box sx={{ mt: 2 }}>
        <button
          type="button"
          onClick={() => setShowContext((open) => !open)}
          style={{
            all: "unset",
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            color: "var(--text-color-secondary)",
          }}
        >
          {showContext ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          <Text kind="body/regular/md">
            Add context (optional, but it changes the severities)
          </Text>
        </button>
      </Box>

      <Collapse in={showContext}>
        <Box sx={{ display: "grid", gap: 2, mt: 2, maxWidth: 720 }}>
          <TextField
            label="What is it for?"
            placeholder="Collects DCGM and NVLink health during rack bring-up and writes a validation report."
            value={purpose}
            onChange={(event) => setPurpose(event.target.value)}
            size="small"
            multiline
            minRows={2}
            disabled={busy}
            helperText="If the code disagrees with this, the report says so — which is often the most useful line in it."
          />
          <TextField
            label="Who depends on it?"
            value={criticality}
            onChange={(event) => setCriticality(event.target.value)}
            size="small"
            select
            disabled={busy}
            helperText="Drives severity. Losing an experiment's state is a nuisance; losing a shared service's state stops a deployment."
          >
            <MenuItem value="">Not stated</MenuItem>
            {CRITICALITY.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="What data does it hold?"
            placeholder="Serial numbers, BMC credentials, customer rack layouts"
            value={dataHandled}
            onChange={(event) => setDataHandled(event.target.value)}
            size="small"
            disabled={busy}
            helperText="Determines whether the data-security pillar is judged against a tool that holds nothing or one that holds customer information."
          />
        </Box>
      </Collapse>
    </Paper>
  );
}
