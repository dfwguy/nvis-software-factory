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
// ContractExplorerView.tsx — the seven NRM entities, and how to consume them.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// The audience for this page is a person who has been told to make their tool interoperate and
// has ten minutes. So it leads with the four fetches that let an agent do the work, and only
// then explains the model. The alternative -- explaining the model first -- means the useful
// links are below the fold for the reader who most needs them.
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import { Button, Text } from "@nvidia/foundations-react-core";
import { ChevronRight, Download, FileJson, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import { CopyButton } from "../components/CopyButton";
import { ErrorBanner, Loading, Page, SectionHeading } from "../components/Feedback";
import { useApi } from "../hooks/useApi";
import { CONTRACT_PATH, entityPath } from "../routes";
import { AGENT_PACK_URL, BUNDLE_URL, getIndex, OPENAPI_URL } from "../services/contracts";

/** The one-line pitch per entity, for readers who will not open seven schemas. */
const ONE_LINERS: Record<string, string> = {
  "resource-type": "A kind of thing. One SKU, described once — where partner datasheet data lands.",
  resource: "A thing. One of the seventy-two GPUs, pointing at its type.",
  location: "A place. Site, room, row, rack, rack unit.",
  port: "A termination point. Network, power, coolant — all of them.",
  link: "A connection between two ports, with a key derived from its endpoints.",
  domain: "A logical grouping that cuts across the containment tree: an IB fabric, an NVLink domain.",
  "cooling-path": "A coolant route from a CDU to the things it cools.",
};

export function ContractExplorerView() {
  const { data, loading, error } = useApi(getIndex);

  if (loading && !data) return <Page><Loading rows={8} /></Page>;
  if (error) return <Page><ErrorBanner message={error} /></Page>;
  if (!data) return null;

  return (
    <Page>
      <SectionHeading
        title="NVIS Resource Model"
        detail={
          <>
            Version <span className="nvsf-code">{data.nrm_version}</span> — one identity for every
            physical and logical thing in an AI factory, from a transceiver to a rack, so two teams
            can exchange inventory without agreeing on a database.
          </>
        }
      />

      {/* ── Start here ────────────────────────────────────────────────────────────────── */}
      <Paper variant="outlined" sx={{ p: 3, mb: 4 }}>
        <Text kind="body/bold/md" style={{ display: "block", marginBottom: 4 }}>
          Integrating a tool? Start here.
        </Text>
        <Text
          kind="body/regular/sm"
          style={{ color: "var(--text-color-secondary)", display: "block", marginBottom: 16 }}
        >
          The agent pack is written for a coding agent: it carries the schemas plus the five rules
          that are not inferable from them. Point your agent at it before writing any mapping code.
        </Text>
        <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
          <Button kind="primary" color="brand" size="small" asChild>
            <a href={AGENT_PACK_URL}>
              <Sparkles size={14} />
              Agent pack (Markdown)
            </a>
          </Button>
          <Button kind="secondary" size="small" asChild>
            <a href={BUNDLE_URL}>
              <Download size={14} />
              Whole contract, one fetch
            </a>
          </Button>
          <Button kind="secondary" size="small" asChild>
            <a href={OPENAPI_URL}>
              <FileJson size={14} />
              OpenAPI description
            </a>
          </Button>
          <CopyButton
            text={`curl -sS ${window.location.origin}${AGENT_PACK_URL}`}
            label="Copy curl"
          />
        </Box>
      </Paper>

      {/* ── Entities ──────────────────────────────────────────────────────────────────── */}
      <SectionHeading
        title="Entities"
        detail="Seven, and no more than seven. Each one earns its place by being something two teams need to refer to by the same name."
      />
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { md: "1fr 1fr" }, mb: 4 }}>
        {data.entities.map((entity) => (
          <Paper key={entity.name} variant="outlined" sx={{ p: 2.5 }}>
            <Box sx={{ display: "flex", justifyContent: "space-between", gap: 1 }}>
              <Text kind="body/bold/sm">{entity.title}</Text>
              <Text kind="body/regular/xs" style={{ color: "var(--text-color-secondary)" }}>
                {entity.required.length} required
              </Text>
            </Box>
            <Text
              kind="body/regular/sm"
              style={{ display: "block", marginTop: 6, minHeight: 40 }}
            >
              {ONE_LINERS[entity.name] ?? entity.description.split("\n\n")[0]}
            </Text>
            <Box sx={{ mt: 1.5, display: "flex", gap: 2, alignItems: "center" }}>
              <Link
                to={entityPath(entity.name)}
                style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
              >
                <Text kind="body/regular/sm">Fields and reasoning</Text>
                <ChevronRight size={14} />
              </Link>
              <a href={`/api/contracts/nrm/${data.nrm_version}/${entity.schema}`}>
                <Text kind="body/regular/xs" style={{ color: "var(--text-color-secondary)" }}>
                  raw schema
                </Text>
              </a>
            </Box>
          </Paper>
        ))}
      </Box>

      {/* ── Supporting schemas ────────────────────────────────────────────────────────── */}
      <SectionHeading
        title="Supporting schemas"
        detail="Real schemas, but not entities. Listed apart so nobody models a `common` — it holds the shared definitions the entities reference."
      />
      <Paper variant="outlined" sx={{ p: 2.5, mb: 4 }}>
        <Box sx={{ display: "grid", gap: 1 }}>
          {data.supporting.map((entity) => (
            <Box key={entity.name} sx={{ display: "flex", gap: 2, alignItems: "baseline" }}>
              <Text kind="body/bold/xs" style={{ minWidth: 90 }}>
                {entity.title}
              </Text>
              <Text kind="body/regular/sm" style={{ flexGrow: 1 }}>
                {entity.description.split("\n\n")[0]}
              </Text>
              <a href={`/api/contracts/nrm/${data.nrm_version}/${entity.schema}`}>
                <Text kind="body/regular/xs" style={{ color: "var(--text-color-secondary)" }}>
                  raw
                </Text>
              </a>
            </Box>
          ))}
        </Box>
      </Paper>

      {/* ── What to know before mapping ───────────────────────────────────────────────── */}
      <SectionHeading
        title="What the schemas do not tell you"
        detail="Four decisions that are the difference between a mapping that works and one that looks right."
      />
      <Box sx={{ display: "grid", gap: 2, mb: 4 }}>
        <Decision
          title="Primary keys are opaque; real identity goes in identifiers[]"
          body="Mint a UUIDv7 and never derive it from a serial, a hostname or a GUID. Hardware gets renamed, re-serialized and replaced under warranty, and a derived key changes when it should not. The serial still matters — it goes in identifiers[] verbatim, uppercase and separators intact, because its only job is to match a source system exactly."
        />
        <Decision
          title="Every record is either expected or observed"
          body="expected for anything from a plan, a cabling file or an order. observed for anything measured or discovered. The difference between the two IS the validation report: plan versus reality becomes a set difference rather than a script. Defaulting everything to observed makes a planning import look like a completed deployment."
        />
        <Decision
          title="A link's key is derived from its endpoints, sorted"
          body="A cabling file lists a link switch-first; a discovery sweep reports the same link node-first. Without a canonical key each one reads as both a missing cable and an unexpected one. Normalize each endpoint, sort the pair, join with a colon — and validation rejects a key that disagrees with the ports it points at."
        />
        <Decision
          title="Type facts and instance facts do not mix"
          body="Rack units, TDP and coolant requirements belong to a SKU, not to each unit of it. Copying them onto every unit guarantees the copies disagree, and correcting a published power figure becomes an UPDATE across thousands of rows instead of one."
        />
      </Box>

      <Paper variant="outlined" sx={{ p: 3 }}>
        <Text kind="body/bold/md" style={{ display: "block", marginBottom: 8 }}>
          Before you claim conformance
        </Text>
        <Text kind="body/regular/sm" style={{ display: "block", marginBottom: 12 }}>
          Post your output to the validator. It checks the schema, then the three things a schema
          cannot express: every reference resolves, containment has no cycles, and link classes and
          keys agree with their endpoints. Passing the schema and failing those is the normal
          outcome of a first attempt.
        </Text>
        <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
          <Button kind="primary" size="small" asChild>
            <Link to={`${CONTRACT_PATH}/validate`}>Open the validator</Link>
          </Button>
          <Button kind="secondary" size="small" asChild>
            <Link to={`${CONTRACT_PATH}/crosswalk`}>See existing crosswalks</Link>
          </Button>
        </Box>
      </Paper>
    </Page>
  );
}

function Decision({ title, body }: { title: string; body: string }) {
  return (
    <Paper variant="outlined" sx={{ p: 2.5 }}>
      <Text kind="body/bold/sm" style={{ display: "block", marginBottom: 4 }}>
        {title}
      </Text>
      <Text kind="body/regular/sm">{body}</Text>
    </Paper>
  );
}
