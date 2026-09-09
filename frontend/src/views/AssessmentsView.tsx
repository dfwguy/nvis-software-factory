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
// AssessmentsView.tsx — every run, newest first.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tooltip from "@mui/material/Tooltip";
import { Tag, Text } from "@nvidia/foundations-react-core";
import { useCallback } from "react";
import { useNavigate } from "react-router-dom";

import { EmptyState, ErrorBanner, Loading, Page, SectionHeading } from "../components/Feedback";
import { StatusTag } from "../components/labels";
import { useApi, usePolling } from "../hooks/useApi";
import { duration, repoLabel, when } from "../lib/format";
import { assessmentPath, REPOSITORIES_PATH } from "../routes";
import { listAssessments, listRepositories } from "../services/factory";
import type { AssessmentList } from "../types/api";

/** Keep polling while anything is in flight, then stop. A finished list does not change. */
const stillMoving = (data: AssessmentList | null) =>
  Boolean(data?.in_flight.length) ||
  Boolean(data?.assessments.some((a) => !["complete", "failed", "cancelled"].includes(a.status)));

export function AssessmentsView() {
  const navigate = useNavigate();

  const loader = useCallback(
    (signal: AbortSignal) => listAssessments({ limit: 100 }, signal),
    [],
  );
  const { data, loading, error } = usePolling(loader, stillMoving, 5000);

  // Fetched alongside so the table can show which repository each run was of. The assessments
  // endpoint returns a repository_id, and an id is not something a reader can recognize.
  const repositories = useApiRepositories();

  if (loading && !data) return <Page><Loading rows={6} /></Page>;

  return (
    <Page>
      <SectionHeading
        title="Assessment runs"
        detail={
          data?.in_flight.length
            ? `${data.in_flight.length} running now. This page refreshes itself while anything is in flight.`
            : "Nothing running. Newest first."
        }
      />

      {error && <ErrorBanner message={error} />}

      {!data?.assessments.length ? (
        <EmptyState
          message="No assessments yet"
          hint={
            <>
              Start one from the{" "}
              <button
                type="button"
                onClick={() => navigate(REPOSITORIES_PATH)}
                style={{ all: "unset", cursor: "pointer", textDecoration: "underline" }}
              >
                Repositories
              </button>{" "}
              page.
            </>
          }
        />
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Repository</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Started</TableCell>
                <TableCell>Took</TableCell>
                <TableCell>Baseline</TableCell>
                <TableCell>By</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.assessments.map((assessment) => {
                const started = when(assessment.created_at);
                const live = data.in_flight.includes(assessment.id);
                const repository = repositories.get(assessment.repository_id);
                return (
                  <TableRow
                    key={assessment.id}
                    hover
                    sx={{ cursor: "pointer" }}
                    onClick={() => navigate(assessmentPath(assessment.id))}
                  >
                    <TableCell>{repository ? repoLabel(repository) : assessment.repository_id}</TableCell>
                    <TableCell>
                      <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
                        <StatusTag status={assessment.status} />
                        {/* "queued" with a worker on it and "queued" with nothing on it look
                            identical otherwise, and the difference is what tells an operator
                            whether the pool is stuck. */}
                        {live && (
                          <Tag color="teal" kind="outline" readOnly density="compact">
                            on a worker
                          </Tag>
                        )}
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Tooltip title={started.absolute}>
                        <span>{started.relative}</span>
                      </Tooltip>
                    </TableCell>
                    <TableCell>{duration(assessment.started_at, assessment.finished_at)}</TableCell>
                    <TableCell>
                      <span className="nvsf-code">{assessment.standards_version ?? "—"}</span>
                    </TableCell>
                    <TableCell>{assessment.created_by}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Box sx={{ mt: 2 }}>
        <Text kind="body/regular/md" style={{ color: "var(--text-color-secondary)" }}>
          A failed run can be retried from its detail page, and resumes from its last completed
          reasoning pass rather than starting over.
        </Text>
      </Box>
    </Page>
  );
}

/** Repository lookup by id, so rows can name what they assessed. */
function useApiRepositories() {
  const { data } = useApi(listRepositories);
  return new Map((data?.repositories ?? []).map((repository) => [repository.id, repository]));
}
