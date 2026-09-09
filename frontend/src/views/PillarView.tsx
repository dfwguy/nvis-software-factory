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
// PillarView.tsx — one pillar in full: criteria, detectors, remediation patterns.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import { Text } from "@nvidia/foundations-react-core";
import { ChevronLeft } from "lucide-react";
import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";

import { CopyButton } from "../components/CopyButton";
import { ErrorBanner, Loading, Page, SectionHeading } from "../components/Feedback";
import { DetectorTag, SeverityTag } from "../components/labels";
import { Markdown } from "../components/Markdown";
import { useApi } from "../hooks/useApi";
import { GOLDEN_PATH } from "../routes";
import { getPillar } from "../services/platform";

export function PillarView() {
  const { pillarId = "" } = useParams<{ pillarId: string }>();
  const loader = useCallback((signal: AbortSignal) => getPillar(pillarId, signal), [pillarId]);
  const { data, loading, error } = useApi(loader, [pillarId]);

  if (loading && !data) return <Page><Loading rows={8} /></Page>;
  if (error) {
    return (
      <Page>
        <ErrorBanner message={error} />
        <Link to={GOLDEN_PATH}>Back to the golden path</Link>
      </Page>
    );
  }
  if (!data) return null;

  const { pillar } = data;

  return (
    <Page width="comfortable">
      <Box sx={{ mb: 2 }}>
        <Link to={GOLDEN_PATH} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <ChevronLeft size={14} />
          <Text kind="body/regular/sm">All pillars</Text>
        </Link>
      </Box>

      <SectionHeading
        title={pillar.title}
        detail={
          <>
            <span className="nvsf-code">{pillar.id}</span> · baseline{" "}
            <span className="nvsf-code">{data.version}</span> · worst possible severity{" "}
            <SeverityTag severity={pillar.severity_ceiling} />
          </>
        }
        action={
          // The whole pillar as Markdown, for pasting into an agent session alongside the
          // repository. This is the "drive the agent from our standards" path: the criteria are
          // written to be actionable by a model, not just readable by a person.
          <CopyButton text={pillar.body} label="Copy for an agent" />
        }
      />

      <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
        <Text kind="body/bold/sm" style={{ display: "block", marginBottom: 8 }}>
          Criteria at a glance
        </Text>
        <Box sx={{ display: "grid", gap: 1 }}>
          {pillar.criteria.map((criterion) => (
            <Box
              key={criterion.id}
              sx={{ display: "flex", gap: 1.5, alignItems: "baseline", flexWrap: "wrap" }}
            >
              <Text kind="body/bold/xs" style={{ minWidth: 28 }}>
                {criterion.id}
              </Text>
              <Text kind="body/regular/sm" style={{ flexGrow: 1, minWidth: 240 }}>
                {criterion.title}
              </Text>
              <DetectorTag detector={criterion.detector} />
            </Box>
          ))}
        </Box>
        {pillar.detectors.length > 0 && (
          <Text
            kind="body/regular/xs"
            style={{ color: "var(--text-color-secondary)", display: "block", marginTop: 12 }}
          >
            Scanners for this pillar: {pillar.detectors.join(", ")}
          </Text>
        )}
      </Paper>

      {/* The body carries the reasoning and the remediation patterns, and it is the same text the
          prompt gives the model. A reader who disagrees with a judgement can read exactly what
          the model was told. */}
      <Paper variant="outlined" sx={{ p: 3 }}>
        <Markdown source={pillar.body} />
      </Paper>
    </Page>
  );
}
