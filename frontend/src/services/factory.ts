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
// factory.ts — repositories and assessments.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// Every network call the factory views make goes through here. Views do not build URLs: a URL in
// a component is a URL that gets copied into the next component with a typo in it.
import { apiJson, postJson } from "../lib/apiFetch";
import type {
  AssessmentDetail,
  AssessmentList,
  CreatedAssessment,
  ProvenanceDetail,
  RepositoryDetail,
  RepositoryList,
} from "../types/api";

export interface IntakeAnswers {
  purpose?: string;
  audience?: string;
  criticality?: string;
  data_handled?: string;
  notes?: string;
}

export function listRepositories(signal?: AbortSignal): Promise<RepositoryList> {
  return apiJson<RepositoryList>("/api/repositories/", { signal });
}

export function getRepository(id: string, signal?: AbortSignal): Promise<RepositoryDetail> {
  return apiJson<RepositoryDetail>(`/api/repositories/${encodeURIComponent(id)}`, { signal });
}

export function addRepository(url: string, notes?: string): Promise<{ repository: RepositoryDetail["repository"] }> {
  return postJson("/api/repositories/", { url, notes: notes || undefined });
}

export function listAssessments(
  options: { repositoryId?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<AssessmentList> {
  const query = new URLSearchParams();
  if (options.repositoryId) query.set("repository_id", options.repositoryId);
  if (options.limit) query.set("limit", String(options.limit));
  const suffix = query.size ? `?${query}` : "";
  return apiJson<AssessmentList>(`/api/assessments/${suffix}`, { signal });
}

export function getAssessment(id: string, signal?: AbortSignal): Promise<AssessmentDetail> {
  return apiJson<AssessmentDetail>(`/api/assessments/${encodeURIComponent(id)}`, { signal });
}

export function getProvenance(id: string, signal?: AbortSignal): Promise<ProvenanceDetail> {
  return apiJson<ProvenanceDetail>(
    `/api/assessments/${encodeURIComponent(id)}/provenance`,
    { signal },
  );
}

/**
 * Start a run.
 *
 * Either target works: an already-registered repository, or a URL to register and assess in one
 * step. The second is what an SA arriving with a link actually wants, and making them register
 * first would be a step that exists only because of how the data is stored.
 */
export function startAssessment(
  target: { repositoryId?: string; url?: string; ref?: string } & IntakeAnswers,
): Promise<CreatedAssessment> {
  const { repositoryId, url, ref, ...intake } = target;
  return postJson<CreatedAssessment>("/api/assessments/", {
    repository_id: repositoryId,
    url,
    ref: ref || undefined,
    ...intake,
  });
}

export function retryAssessment(id: string): Promise<{ resuming_from: string[]; note: string }> {
  return postJson(`/api/assessments/${encodeURIComponent(id)}/retry`, {});
}

export function cancelAssessment(id: string): Promise<{ note: string }> {
  return postJson(`/api/assessments/${encodeURIComponent(id)}/cancel`, {});
}

/** A download URL, not a fetch. The browser is better at saving a file than we are. */
export function artifactUrl(assessmentId: string, filename: string): string {
  return `/api/assessments/${encodeURIComponent(assessmentId)}/artifacts/${encodeURIComponent(filename)}`;
}
