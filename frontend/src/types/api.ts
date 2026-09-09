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
// api.ts — the response shapes, hand-written to match backend/api/.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// Hand-written rather than generated. /api/openapi.json describes paths, permissions and
// parameters, but not response schemas -- it is generated from the route table, and inventing
// response schemas there to feed a codegen step would mean maintaining a second description of
// every payload. These types are checked against the real API by the service-layer tests.
//
// The model-authored sections (architecture, judgements, remediation, open questions) are typed
// with every field optional. They come from a language model, and while the prompt asks for a
// specific object, a UI that throws when one key is missing turns a slightly-short answer into a
// blank page. Rendering is defensive everywhere these appear.

export type AssessmentStatus =
  | "queued"
  | "acquiring"
  | "scanning"
  | "reasoning"
  | "rendering"
  | "complete"
  | "failed"
  | "cancelled";

export type Severity = "blocker" | "major" | "minor" | "info";
export type FindingOrigin = "scanner" | "model" | "escalated";
export type Verdict = "pass" | "concerns" | "fail" | "undetermined";
export type Detector = "yes" | "partial" | "no";

export interface Repository {
  id: string;
  url: string;
  forge: string | null;
  namespace: string | null;
  name: string | null;
  default_branch: string | null;
  added_at: string;
  added_by: string;
  notes: string | null;
}

export interface Assessment {
  id: string;
  repository_id: string;
  status: AssessmentStatus;
  ref: string | null;
  commit_sha: string | null;
  evidence_hash: string | null;
  standards_version: string | null;
  intake: Record<string, string>;
  failure: { reason: string | null; detail: string | null; retryable: boolean } | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  created_by: string;
}

export interface Progress {
  assessment_id: string;
  stage: string;
  passes_total: number;
  passes_done: number;
  detail: string;
}

export interface Finding {
  id: string;
  pillar_id: string;
  criterion: string | null;
  severity: Severity;
  title: string;
  detail: string;
  citation: string | null;
  file_path: string | null;
  line_start: number | null;
  line_end: number | null;
  origin: FindingOrigin;
  escalated_from: Severity | null;
  detector: string | null;
  remediation: string | null;
}

export interface LlmCall {
  id: string;
  pass_name: string;
  model: string;
  prompt_version: string;
  temperature: number;
  evidence_hash: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  duration_ms: number | null;
  status: string;
  error: string | null;
  created_at: string;
  raw_response?: string | null;
}

export interface Artifact {
  kind: string;
  filename: string;
  bytes: number;
  sha256: string;
  created_at: string;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  calls: number;
}

// ── Model-authored sections ─────────────────────────────────────────────────────────────────

export interface Architecture {
  purpose?: string;
  archetype?: string;
  components?: { name?: string; role?: string; evidence?: string }[];
  state?: { what_state_exists?: string; where_it_lives?: string; evidence?: string };
  external_dependencies?: { what?: string; how?: string; evidence?: string }[];
  entry_points?: { kind?: string; name?: string; evidence?: string }[];
  who_depends_on_it?: string;
  not_determinable?: string[];
}

export interface CriterionOutcome {
  id?: string;
  outcome?: "pass" | "fail" | "undetermined" | "not-applicable";
  reasoning?: string;
  evidence?: string;
}

export interface Judgement {
  verdict?: Verdict;
  summary?: string;
  criteria?: CriterionOutcome[];
  escalations?: { finding_title?: string; to_severity?: Severity; why?: string }[];
  suspected_false_positives?: { finding_title?: string; why?: string }[];
  open_questions?: string[];
}

export interface RemediationStep {
  title?: string;
  why?: string;
  where?: string;
  what_to_do?: string;
  verify?: string;
  effort?: string;
  addresses?: string[];
}

export interface Remediation {
  headline?: string;
  posture?: "safe-to-depend-on" | "needs-work-before-others-depend-on-it" | "do-not-deploy";
  posture_reason?: string;
  immediate?: RemediationStep[];
  next?: RemediationStep[];
  later?: RemediationStep[];
  do_not_do?: { suggestion?: string; why_not?: string }[];
  agent_preamble?: string;
}

export interface OpenQuestions {
  questions?: {
    question?: string;
    why_it_matters?: string;
    if_yes?: string;
    if_no?: string;
    affects?: string[];
  }[];
  assumptions_made?: {
    assumption?: string;
    chosen_because?: string;
    if_wrong?: string;
  }[];
}

// ── Envelopes ───────────────────────────────────────────────────────────────────────────────

export interface Envelope {
  ok: true;
}

export interface RepositoryList extends Envelope {
  repositories: Repository[];
  total: number;
  limit: number;
  offset: number;
}

export interface RepositoryDetail extends Envelope {
  repository: Repository;
  assessments: Assessment[];
}

export interface AssessmentList extends Envelope {
  assessments: Assessment[];
  /** Ids of the runs the worker pool is executing right now, not a count -- so the list can mark
   *  the specific rows that are live without a second request. */
  in_flight: string[];
  limit: number;
  offset: number;
}

export interface AssessmentDetail extends Envelope {
  assessment: Assessment;
  progress: Progress;
  pass_states: Record<string, string>;
  architecture: Architecture | null;
  judgements: Record<string, Judgement>;
  remediation: Remediation | null;
  open_questions: OpenQuestions | null;
  findings: Finding[];
  severity_counts: Record<Severity, number>;
  artifacts: Artifact[];
  token_usage: TokenUsage;
}

export interface ProvenanceDetail extends Envelope {
  assessment: Assessment;
  llm_calls: LlmCall[];
  token_usage: TokenUsage;
  pass_states: Record<string, string>;
  evidence: Record<string, unknown> | null;
}

export interface CreatedAssessment extends Envelope {
  assessment: Assessment;
  repository: Repository;
}

// ── Standards ───────────────────────────────────────────────────────────────────────────────

export interface Criterion {
  id: string;
  title: string;
  detector: Detector;
  judgement_only: boolean;
  body: string;
}

export interface Pillar {
  id: string;
  title: string;
  order: number;
  severity_ceiling: Severity;
  detectors: string[];
  criteria: Criterion[];
  body?: string;
}

export interface StandardsIndex extends Envelope {
  version: string;
  overview: string;
  pillars: Pillar[];
}

export interface PillarDetail extends Envelope {
  version: string;
  pillar: Pillar & { body: string };
}

// ── Contracts ───────────────────────────────────────────────────────────────────────────────

export interface ContractEntity {
  name: string;
  title: string;
  description: string;
  required: string[];
  schema: string;
}

export interface ContractIndex extends Envelope {
  nrm_version: string;
  published_versions: string[];
  default_version: string;
  entities: ContractEntity[];
  /** `common` and `bundle`: real schemas, but not entities. Listed apart so the explorer does
   *  not offer them as things to model, which is the mistake they invite. */
  supporting: ContractEntity[];
  links: {
    bundle: string;
    agent_pack: string;
    crosswalks: string;
    validate: string;
    openapi: string;
    schema_base: string;
  };
}

export interface JsonSchema {
  $id?: string;
  title?: string;
  description?: string;
  type?: string;
  required?: string[];
  properties?: Record<string, JsonSchemaProperty>;
  $defs?: Record<string, JsonSchema>;
  additionalProperties?: boolean;
}

export interface JsonSchemaProperty {
  type?: string | string[];
  description?: string;
  format?: string;
  enum?: string[];
  $ref?: string;
  items?: JsonSchemaProperty;
  default?: unknown;
  const?: unknown;
  minimum?: number;
  maximum?: number;
}

export interface EntityCoverage {
  direction: string;
  mapped_fields: number;
  /** Fields the contract has that this system cannot carry, each with a stated reason. Reported
   *  rather than hidden: a mapping that silently drops a field is how two systems end up
   *  disagreeing without anyone noticing. */
  documented_gaps: number;
  unreliable_fields: number;
}

export interface SystemCoverage {
  role: string;
  system_version?: string;
  entities: Record<string, EntityCoverage>;
  missing_entities: string[];
  join?: { nrm_field?: string; system_field?: string; note?: string };
}

export interface CrosswalkCoverage extends Envelope {
  nrm_version: string;
  systems: Record<string, SystemCoverage>;
}

export interface CrosswalkField {
  nrm: string;
  system?: string | null;
  direction?: string;
  transform?: string;
  note?: string;
  unreliable?: boolean;
  values?: Record<string, string>;
}

/** An NRM field this system cannot carry, with the reason it cannot. */
export interface CrosswalkGap {
  field: string;
  reason: string;
}

export interface CrosswalkEntity {
  nrm_entity: string;
  system_model: string;
  direction: string;
  note?: string;
  fields: CrosswalkField[];
  /** Required on every mapping, empty list included, so "nothing is unmapped" is an assertion
   *  someone made rather than a section someone forgot. */
  unmapped_nrm?: CrosswalkGap[];
}

export interface Crosswalk {
  crosswalk_version: string;
  nrm_version: string;
  system: string;
  system_version?: string;
  role: string;
  authority?: string;
  join?: { nrm_field?: string; system_field?: string; note?: string };
  entities: CrosswalkEntity[];
  transforms?: Record<string, string>;
  recommended_labels?: Record<string, string>;
}

/** A conformance failure. `pointer` is a JSON Pointer into the payload, so a client can walk
 *  straight to the offending record rather than searching for it by message. */
export interface ValidationProblem {
  pointer: string;
  message: string;
  rule: string;
}

export interface Verdict_ {
  valid: boolean;
  problem_count: number;
  problems: ValidationProblem[];
  counts?: Record<string, number>;
  not_checked?: string[];
  truncated?: boolean;
}

export interface ValidationResult extends Envelope, Verdict_ {
  mode: "bundle" | "record";
  nrm_version: string;
  note?: string;
}

export interface FieldMapping {
  source_field?: string;
  nrm_field?: string;
  transform?: string;
  confidence?: string;
  reasoning?: string;
}

/**
 * The model's proposal *and* the schema's verdict on it, together.
 *
 * Both are in one response because the interesting case is when they disagree: a mapping the
 * model called high-confidence that produced an invalid record. `model_confidence` carries no
 * weight and the UI labels it that way; `adjudication` is the answer.
 */
export interface MappingProposal extends Envelope {
  entity: string;
  nrm_version: string;
  field_map: FieldMapping[];
  identifiers: { format?: string; value?: string; source_field?: string; scope?: string }[];
  record: Record<string, unknown> | null;
  unmapped_source_fields: { field?: string; why?: string }[] | string[];
  unfilled_required_fields: { field?: string; why?: string }[] | string[];
  model_confidence?: string;
  model_confidence_reason?: string;
  adjudication: Verdict_;
  provenance: { model: string; prompt_version: string; temperature: number };
  note: string;
}

// ── Session and health ──────────────────────────────────────────────────────────────────────

export interface Principal {
  subject: string;
  email: string | null;
  display_name: string | null;
  groups: string[];
  /** Roles granted directly by a group claim. */
  roles: string[];
  /** Roles after implication (admin implies member implies viewer). What authorization uses, and
   *  therefore what the UI should reason about. */
  effective_roles: string[];
  /** True when the loopback mock provider issued this session. Surfaced in the UI on purpose:
   *  a deployment accidentally running on the mock must be obvious, not discoverable. */
  is_mock?: boolean;
}

export interface Session extends Envelope {
  user: Principal;
  permissions: string[];
}

export interface HealthCheck {
  ok: boolean;
  detail?: string;
  [key: string]: unknown;
}

export interface Health {
  ok: boolean;
  status: "healthy" | "unhealthy";
  failing: string[];
  checks: Record<string, HealthCheck>;
}

export interface LlmProbe {
  ok: boolean;
  reachable: boolean;
  model?: string;
  endpoint?: string;
  detail?: string;
  latency_ms?: number;
}
