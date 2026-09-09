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
// contracts.ts — the NRM contract surface.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import { apiJson, postJson } from "../lib/apiFetch";
import type {
  ContractIndex,
  Crosswalk,
  CrosswalkCoverage,
  JsonSchema,
  MappingProposal,
  ValidationResult,
} from "../types/api";

export function getIndex(signal?: AbortSignal): Promise<ContractIndex> {
  return apiJson<ContractIndex>("/api/contracts/index.json", { signal });
}

/**
 * One entity schema.
 *
 * The version is a parameter everywhere rather than a default, because the whole point of
 * publishing v0.1 is that v0.2 can exist next to it. A UI that silently reads "the current one"
 * is a UI that will show a team the wrong contract the week after a bump.
 */
export function getSchema(
  entity: string,
  version: string,
  signal?: AbortSignal,
): Promise<JsonSchema> {
  return apiJson<JsonSchema>(
    `/api/contracts/nrm/${encodeURIComponent(version)}/${encodeURIComponent(entity)}.schema.json`,
    { signal },
  );
}

export function getCoverage(signal?: AbortSignal): Promise<CrosswalkCoverage> {
  return apiJson<CrosswalkCoverage>("/api/contracts/crosswalk", { signal });
}

export function getCrosswalk(system: string, signal?: AbortSignal): Promise<Crosswalk> {
  return apiJson<Crosswalk>(`/api/contracts/crosswalk/${encodeURIComponent(system)}`, { signal });
}

export function getFixture(
  name: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  return apiJson<Record<string, unknown>>(
    `/api/contracts/fixtures/${encodeURIComponent(name)}.json`,
    { signal },
  );
}

/**
 * Adjudicate a payload. No model in this path, by design -- conformance is decidable.
 *
 * A bundle is submitted as-is. A single record is wrapped as `{entity, record}`, which is the
 * mode a team integrating incrementally needs: they have one Resource, not a rack. The endpoint
 * reports which checks that mode cannot perform rather than passing silently.
 */
export function validate(payload: unknown): Promise<ValidationResult> {
  return postJson<ValidationResult>("/api/contracts/validate", payload);
}

export function validateRecord(entity: string, record: unknown): Promise<ValidationResult> {
  return postJson<ValidationResult>("/api/contracts/validate", { entity, record });
}

/** Ask the model to propose a mapping. It proposes; the validator above decides. */
export function proposeMapping(input: {
  sample: unknown;
  entity?: string;
  system?: string;
  description?: string;
}): Promise<MappingProposal> {
  return postJson<MappingProposal>("/api/contracts/map", input);
}

export const AGENT_PACK_URL = "/api/contracts/agent-pack.md";
export const BUNDLE_URL = "/api/contracts/bundle";
export const OPENAPI_URL = "/api/openapi.json";
