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
// PlatformView.tsx — what this deployment is, and whether it can do its job.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// The page an SA opens when an assessment failed and they want to know whether it was their repo
// or our deployment. It therefore leads with the reasoning endpoint, which is the dependency that
// actually stops runs, and it shows the operator's own effective roles -- "why can I not start a
// run" is a permissions question far more often than a health one.
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableRow from "@mui/material/TableRow";
import Tooltip from "@mui/material/Tooltip";
import { Banner, Button, Tag, Text } from "@nvidia/foundations-react-core";
import { CheckCircle2, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ErrorBanner, Loading, Page, SectionHeading } from "../components/Feedback";
import { useApi } from "../hooks/useApi";
import { bytes, millis } from "../lib/format";
import { GOLDEN_PATH, pillarPath } from "../routes";
import { getHealth, getStandards, probeLlm } from "../services/platform";
import { useSession } from "../context/SessionContext";
import type { HealthCheck, LlmProbe } from "../types/api";

export function PlatformView() {
  const health = useApi(getHealth);
  const standards = useApi(getStandards);
  const { user, permissions } = useSession();

  if (health.loading && !health.data) return <Page><Loading rows={8} /></Page>;
  if (health.error && !health.data) return <Page><ErrorBanner message={health.error} /></Page>;

  const checks = Object.entries(health.data?.checks ?? {});

  return (
    <Page>
      <SectionHeading
        title="Platform"
        detail="What this deployment is running, and whether it can complete an assessment."
      />

      {health.data && !health.data.ok && (
        <Box sx={{ mb: 3 }}>
          <Banner status="error">
            <Text kind="body/bold/sm" style={{ display: "block" }}>
              Unhealthy: {health.data.failing.join(", ")}.
            </Text>
            <Text kind="body/regular/sm">
              These are required dependencies, so <span className="nvsf-code">/api/health</span>{" "}
              is answering 503 and an orchestrator will treat this instance as unavailable.
            </Text>
          </Banner>
        </Box>
      )}

      <LlmPanel />

      <SectionHeading title="Dependencies" />
      <Paper variant="outlined" sx={{ mb: 4 }}>
        <Table size="small">
          <TableBody>
            {checks.map(([name, check]) => (
              <TableRow key={name}>
                <TableCell sx={{ width: 40 }}>
                  {check.ok ? (
                    <CheckCircle2 size={16} color="var(--state-ok)" />
                  ) : (
                    <XCircle size={16} color="var(--state-bad)" />
                  )}
                </TableCell>
                <TableCell sx={{ width: 160 }}>
                  <Text kind="body/bold/sm">{name}</Text>
                </TableCell>
                <TableCell>
                  <CheckDetail name={name} check={check} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      <SectionHeading
        title="Quality baseline"
        detail={
          <>
            Every judgement this deployment has ever published was made against this version. A
            finding read without it is not reproducible.
          </>
        }
      />
      <Paper variant="outlined" sx={{ p: 2.5, mb: 4 }}>
        {standards.data ? (
          <>
            <Text kind="body/regular/sm" style={{ display: "block", marginBottom: 8 }}>
              <span className="nvsf-code">standards/</span> version{" "}
              <span className="nvsf-code">{standards.data.version}</span> ·{" "}
              {standards.data.pillars.length} pillars ·{" "}
              <Link to={GOLDEN_PATH}>read the baseline</Link>
            </Text>
            <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap" }}>
              {standards.data.pillars.map((pillar) => (
                <Link key={pillar.id} to={pillarPath(pillar.id)}>
                  <Tag color="gray" kind="outline" readOnly density="compact">
                    {pillar.title}
                  </Tag>
                </Link>
              ))}
            </Box>
          </>
        ) : (
          <Loading rows={2} />
        )}
      </Paper>

      <SectionHeading
        title="You"
        detail="Roles come from your identity provider group claims; this application does not grant them."
      />
      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Text kind="body/regular/sm" style={{ display: "block" }}>
          {user?.display_name ?? user?.email ?? user?.subject ?? "not signed in"}
        </Text>
        <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap", mt: 1, mb: 1 }}>
          {(user?.effective_roles ?? []).map((role) => (
            <Tag key={role} color="green" kind="outline" readOnly density="compact">
              {role}
            </Tag>
          ))}
        </Box>
        {/* Roles after implication, not the raw claim. The raw claim is what an admin edits; the
            effective set is what actually decides a request, and mixing them up is the source of
            "but I am in the group" tickets. */}
        {user?.roles?.length && user.roles.join() !== user.effective_roles.join() ? (
          <Text
            kind="body/regular/xs"
            style={{ color: "var(--text-color-secondary)", display: "block" }}
          >
            granted by group claim: {user.roles.join(", ")} — the rest follow by implication
          </Text>
        ) : null}
        <Tooltip title={[...permissions].sort().join(", ")}>
          <span>
            <Text
              kind="body/regular/xs"
              style={{ color: "var(--text-color-secondary)", display: "block", marginTop: 8 }}
            >
              {permissions.size} actions permitted
            </Text>
          </span>
        </Tooltip>
      </Paper>
    </Page>
  );
}

/** Reachability, on demand. It costs a round trip to a third party, so it is never polled. */
function LlmPanel() {
  const [probe, setProbe] = useState<LlmProbe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setProbe(await probeLlm());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The probe could not be sent");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <SectionHeading
        title="Reasoning endpoint"
        detail="Required. Without it an assessment fails rather than falling back to a scanner-only report."
        action={
          <Button kind="secondary" size="small" onClick={() => void run()} disabled={busy}>
            {busy ? "Probing…" : "Probe now"}
          </Button>
        }
      />
      <Paper variant="outlined" sx={{ p: 2.5, mb: 4 }}>
        {error && <ErrorBanner message={error} />}
        {probe ? (
          <>
            <Box sx={{ display: "flex", gap: 1, alignItems: "center", mb: 1 }}>
              {probe.reachable ? (
                <CheckCircle2 size={16} color="var(--state-ok)" />
              ) : (
                <XCircle size={16} color="var(--state-bad)" />
              )}
              <Text kind="body/bold/sm">
                {probe.reachable ? "Reachable" : "Not reachable"}
              </Text>
              {probe.latency_ms !== undefined && (
                <Text kind="body/regular/xs" style={{ color: "var(--text-color-secondary)" }}>
                  {millis(probe.latency_ms)}
                </Text>
              )}
            </Box>
            <Text kind="body/regular/sm" style={{ display: "block" }}>
              <span className="nvsf-code">{probe.model ?? "no model configured"}</span>
              {probe.endpoint ? (
                <>
                  {" at "}
                  <span className="nvsf-code">{probe.endpoint}</span>
                </>
              ) : null}
            </Text>
            {probe.detail && (
              <Text
                kind="body/regular/sm"
                style={{ color: "var(--text-color-secondary)", display: "block", marginTop: 4 }}
              >
                {probe.detail}
              </Text>
            )}
          </>
        ) : (
          <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
            Not probed. The dependency table below reports whether it is <em>configured</em>;
            probing is what tells you whether it <em>answers</em>.
          </Text>
        )}
      </Paper>
    </>
  );
}

function CheckDetail({ name, check }: { name: string; check: HealthCheck }) {
  const facts: string[] = [];

  if (name === "store") {
    if (check.schema_version !== undefined) facts.push(`schema ${String(check.schema_version)}`);
    if (check.journal_mode) facts.push(`journal ${String(check.journal_mode)}`);
    if (typeof check.bytes === "number") facts.push(bytes(check.bytes));
  }
  if (name === "migrations" && Array.isArray(check.pending) && check.pending.length) {
    facts.push(`pending: ${check.pending.join(", ")}`);
  }
  if (name === "backups") {
    facts.push(check.configured ? "configured" : "not configured");
    if (check.newest) facts.push(`newest ${String(check.newest)}`);
    if (check.count !== undefined) facts.push(`${String(check.count)} snapshots`);
  }
  if (name === "identity" && check.mode) facts.push(String(check.mode));
  if (name === "llm" && check.model) facts.push(String(check.model));

  return (
    <>
      <Text kind="body/regular/sm" style={{ display: "block" }}>
        {facts.join(" · ") || (check.ok ? "ok" : "unavailable")}
      </Text>
      {typeof check.detail === "string" && check.detail && (
        <Text
          kind="body/regular/xs"
          style={{ color: "var(--text-color-secondary)", display: "block" }}
        >
          {check.detail}
        </Text>
      )}
      {/* A warning that is true but not fatal. The mock identity provider being active is the
          case this exists for: it must be impossible to miss without failing the check. */}
      {typeof check.warning === "string" && check.warning && (
        <Text
          kind="body/regular/xs"
          style={{ color: "var(--state-warn)", display: "block" }}
        >
          {check.warning}
        </Text>
      )}
      {name === "backups" && check.stale === true && (
        <Text kind="body/regular/xs" style={{ color: "var(--state-warn)", display: "block" }}>
          The newest snapshot is older than the configured interval. Not fatal, but this is the
          pillar the factory judges hardest.
        </Text>
      )}
    </>
  );
}
