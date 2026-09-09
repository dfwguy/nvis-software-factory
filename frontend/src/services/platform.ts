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
// platform.ts — session, the published baseline, and health.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import { apiFetch, apiJson } from "../lib/apiFetch";
import type { Health, LlmProbe, PillarDetail, Session, StandardsIndex } from "../types/api";

export function getSession(signal?: AbortSignal): Promise<Session> {
  return apiJson<Session>("/api/auth/me", { signal });
}

export function getStandards(signal?: AbortSignal): Promise<StandardsIndex> {
  return apiJson<StandardsIndex>("/api/standards/", { signal });
}

export function getPillar(id: string, signal?: AbortSignal): Promise<PillarDetail> {
  return apiJson<PillarDetail>(`/api/standards/${encodeURIComponent(id)}`, { signal });
}

/**
 * Health, which answers 503 when a required dependency is down.
 *
 * `apiFetch` rather than `apiJson`: an unhealthy deployment is exactly what this view exists to
 * show, and a 503 here is data, not an error. Throwing on it would blank the one page an
 * operator opens when something is wrong.
 */
export async function getHealth(signal?: AbortSignal): Promise<Health> {
  const response = await apiFetch("/api/health/", { signal });
  return (await response.json()) as Health;
}

export async function probeLlm(signal?: AbortSignal): Promise<LlmProbe> {
  const response = await apiFetch("/api/health/llm", { signal });
  return (await response.json()) as LlmProbe;
}
