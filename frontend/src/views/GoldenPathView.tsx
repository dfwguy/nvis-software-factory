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
// GoldenPathView.tsx — what good looks like, published before anyone is judged against it.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// This page exists so the baseline is not a surprise. An SA can read exactly what will be
// checked, and the criteria they see are the same records the prompts are built from -- same
// loader, same version string, so the page and the assessment cannot drift apart.
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import { Text } from "@nvidia/foundations-react-core";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

import { ErrorBanner, InfoBanner, Loading, Page, SectionHeading } from "../components/Feedback";
import { DetectorTag, SeverityTag } from "../components/labels";
import { Markdown } from "../components/Markdown";
import { useApi } from "../hooks/useApi";
import { pillarPath } from "../routes";
import { getStandards } from "../services/platform";

export function GoldenPathView() {
  const { data, loading, error } = useApi(getStandards);

  if (loading && !data) return <Page><Loading rows={8} /></Page>;
  if (error) return <Page><ErrorBanner message={error} /></Page>;
  if (!data) return null;

  const measured = data.pillars.flatMap((pillar) =>
    pillar.criteria.filter((criterion) => criterion.detector !== "no"),
  ).length;
  const total = data.pillars.reduce((sum, pillar) => sum + pillar.criteria.length, 0);

  return (
    <Page width="comfortable">
      <SectionHeading
        title="The golden path"
        detail={
          <>
            Baseline version <span className="nvsf-code">{data.version}</span> — {total} criteria
            across {data.pillars.length} pillars, {measured} of them checked by a scanner and the
            rest judged from evidence.
          </>
        }
      />

      <InfoBanner>
        The version above is derived from the content of these files. When a criterion changes, the
        version changes with it — which is why every assessment records the version it was judged
        against, and why two runs with different versions are not directly comparable.
      </InfoBanner>

      {data.overview && (
        <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
          <Markdown source={data.overview} />
        </Paper>
      )}

      <Box sx={{ display: "grid", gap: 2 }}>
        {data.pillars.map((pillar) => (
          <Paper key={pillar.id} variant="outlined" sx={{ p: 3 }}>
            <Box
              sx={{
                display: "flex",
                gap: 2,
                alignItems: "baseline",
                justifyContent: "space-between",
                flexWrap: "wrap",
              }}
            >
              <Box>
                <Text kind="body/bold/lg">{pillar.title}</Text>
                <Text
                  kind="body/regular/sm"
                  style={{ color: "var(--text-color-secondary)", display: "block" }}
                >
                  <span className="nvsf-code">{pillar.id}</span> · {pillar.criteria.length} criteria
                </Text>
              </Box>
              <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
                {/* The ceiling is why a missing README can never be reported as a blocker. Stated
                    here so a reader can check that a severity they disagree with was even
                    reachable for this pillar. */}
                <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
                  worst possible
                </Text>
                <SeverityTag severity={pillar.severity_ceiling} />
              </Box>
            </Box>

            <Box sx={{ mt: 2, display: "grid", gap: 1 }}>
              {pillar.criteria.map((criterion) => (
                <Box
                  key={criterion.id}
                  sx={{ display: "flex", gap: 1.5, alignItems: "baseline", flexWrap: "wrap" }}
                >
                  <Text kind="body/bold/sm" style={{ minWidth: 28 }}>
                    {criterion.id}
                  </Text>
                  <Text kind="body/regular/md" style={{ flexGrow: 1, minWidth: 240 }}>
                    {criterion.title}
                  </Text>
                  <DetectorTag detector={criterion.detector} />
                </Box>
              ))}
            </Box>

            <Box sx={{ mt: 2 }}>
              <Link to={pillarPath(pillar.id)} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <Text kind="body/regular/md">Criteria in full, with remediation patterns</Text>
                <ChevronRight size={14} />
              </Link>
            </Box>
          </Paper>
        ))}
      </Box>
    </Page>
  );
}
