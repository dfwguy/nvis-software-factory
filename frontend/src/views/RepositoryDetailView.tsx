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
// RepositoryDetailView.tsx — one repository and every assessment of it.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// The history is the point of this page. "Is this better than it was last quarter" is a question
// about a repository, and it is the question that tells an SA whether the effort they spent on
// remediation actually landed.
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tooltip from "@mui/material/Tooltip";
import { Text } from "@nvidia/foundations-react-core";
import { ExternalLink } from "lucide-react";
import { useCallback } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { EmptyState, ErrorBanner, Loading, Page, SectionHeading } from "../components/Feedback";
import { StatusTag } from "../components/labels";
import { StartAssessmentPanel } from "../components/StartAssessmentPanel";
import { useCan } from "../context/SessionContext";
import { useApi } from "../hooks/useApi";
import { duration, repoLabel, shortSha, when } from "../lib/format";
import { assessmentPath, REPOSITORIES_PATH } from "../routes";
import { getRepository } from "../services/factory";

export function RepositoryDetailView() {
  const { repositoryId = "" } = useParams<{ repositoryId: string }>();
  const navigate = useNavigate();
  const canAssess = useCan("assessment:create");

  const loader = useCallback(
    (signal: AbortSignal) => getRepository(repositoryId, signal),
    [repositoryId],
  );
  const { data, loading, error } = useApi(loader, [repositoryId]);

  if (loading && !data) return <Page><Loading rows={6} /></Page>;
  if (error) {
    return (
      <Page>
        <ErrorBanner message={error} />
        <Link to={REPOSITORIES_PATH}>Back to repositories</Link>
      </Page>
    );
  }
  if (!data) return null;

  const { repository, assessments } = data;
  const registered = when(repository.added_at);

  return (
    <Page>
      <SectionHeading
        title={repoLabel(repository)}
        detail={
          <>
            <a href={repository.url} target="_blank" rel="noreferrer">
              {repository.url} <ExternalLink size={12} style={{ verticalAlign: "middle" }} />
            </a>
            {" · "}
            registered <Tooltip title={registered.absolute}><span>{registered.relative}</span></Tooltip>{" "}
            by {repository.added_by}
          </>
        }
      />

      {repository.notes && (
        <Box sx={{ mb: 3 }}>
          <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
            {repository.notes}
          </Text>
        </Box>
      )}

      {canAssess && (
        <Box sx={{ mb: 4 }}>
          <StartAssessmentPanel
            repositoryId={repository.id}
            repositoryLabel={repoLabel(repository)}
            onStarted={(id) => navigate(assessmentPath(id))}
          />
        </Box>
      )}

      <SectionHeading
        title="Assessment history"
        detail="Oldest at the bottom. Compare the finding counts to see whether remediation landed."
      />

      {!assessments.length ? (
        <EmptyState
          message="Never assessed"
          hint="Start a run above. The first one takes a few minutes; most of it is the reasoning stage."
        />
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Started</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Ref</TableCell>
                <TableCell>Commit</TableCell>
                <TableCell>Baseline</TableCell>
                <TableCell>Took</TableCell>
                <TableCell>By</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {assessments.map((assessment) => {
                const started = when(assessment.created_at);
                return (
                  <TableRow
                    key={assessment.id}
                    hover
                    sx={{ cursor: "pointer" }}
                    onClick={() => navigate(assessmentPath(assessment.id))}
                  >
                    <TableCell>
                      <Tooltip title={started.absolute}>
                        <span>{started.relative}</span>
                      </Tooltip>
                    </TableCell>
                    <TableCell><StatusTag status={assessment.status} /></TableCell>
                    <TableCell>{assessment.ref ?? "default"}</TableCell>
                    <TableCell>
                      <span className="nvsf-code">{shortSha(assessment.commit_sha)}</span>
                    </TableCell>
                    {/* The baseline version belongs in this table, not just on the detail page.
                        Two runs with different finding counts are not comparable if the standard
                        changed between them, and this column is how a reader notices. */}
                    <TableCell>
                      <span className="nvsf-code">{assessment.standards_version ?? "—"}</span>
                    </TableCell>
                    <TableCell>{duration(assessment.started_at, assessment.finished_at)}</TableCell>
                    <TableCell>{assessment.created_by}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Page>
  );
}
