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
// RepositoriesView.tsx — the landing view: register a repository, or assess one now.
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
import { Text } from "@nvidia/foundations-react-core";
import { useNavigate } from "react-router-dom";

import { EmptyState, ErrorBanner, Loading, Page, SectionHeading } from "../components/Feedback";
import { StartAssessmentPanel } from "../components/StartAssessmentPanel";
import { useCan } from "../context/SessionContext";
import { useApi } from "../hooks/useApi";
import { repoLabel, when } from "../lib/format";
import { listRepositories } from "../services/factory";
import { repositoryPath } from "../routes";

export function RepositoriesView() {
  const navigate = useNavigate();
  const { data, loading, error, refresh } = useApi(listRepositories);
  const canAdd = useCan("repository:add");

  return (
    <Page>
      {canAdd ? (
        <Box sx={{ mb: 4 }}>
          <StartAssessmentPanel onStarted={(id) => navigate(`/assessments/${id}`)} />
        </Box>
      ) : (
        <Box sx={{ mb: 3 }}>
          <Text kind="body/regular/md" style={{ color: "var(--text-color-secondary)" }}>
            You have read access. Starting an assessment needs the member role — ask in
            #nvis-software-factory to be added to the group.
          </Text>
        </Box>
      )}

      <SectionHeading
        title="Registered repositories"
        detail={
          data
            ? `${data.total} registered. Registration is separate from assessment because the ` +
              `history of a repository is the interesting part.`
            : undefined
        }
      />

      {error && <ErrorBanner message={error} />}

      {loading && !data ? (
        <Loading rows={5} label="Loading repositories" />
      ) : !data?.repositories.length ? (
        <EmptyState
          message="No repositories yet"
          hint="Paste a GitLab or GitHub URL above. Nothing needs to be configured on the repository side — the clone is read-only, shallow, and no code from it is ever executed."
        />
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Repository</TableCell>
                <TableCell>Forge</TableCell>
                <TableCell>Default branch</TableCell>
                <TableCell>Registered</TableCell>
                <TableCell>By</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.repositories.map((repository) => {
                const registered = when(repository.added_at);
                return (
                  <TableRow
                    key={repository.id}
                    hover
                    sx={{ cursor: "pointer" }}
                    onClick={() => navigate(repositoryPath(repository.id))}
                  >
                    <TableCell>
                      <Tooltip title={repository.url}>
                        <span>{repoLabel(repository)}</span>
                      </Tooltip>
                    </TableCell>
                    <TableCell>{repository.forge ?? "—"}</TableCell>
                    <TableCell>{repository.default_branch ?? "—"}</TableCell>
                    <TableCell>
                      <Tooltip title={registered.absolute}>
                        <span>{registered.relative}</span>
                      </Tooltip>
                    </TableCell>
                    <TableCell>{repository.added_by}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Deliberately not a toast. The list is the thing that changed, so the control that
          refreshes it belongs next to it. */}
      {data && data.total > data.repositories.length && (
        <Box sx={{ mt: 2 }}>
          <Text kind="body/regular/md" style={{ color: "var(--text-color-secondary)" }}>
            Showing {data.repositories.length} of {data.total}.{" "}
            <button type="button" onClick={refresh} style={{ all: "unset", cursor: "pointer", textDecoration: "underline" }}>
              Refresh
            </button>
          </Text>
        </Box>
      )}
    </Page>
  );
}
