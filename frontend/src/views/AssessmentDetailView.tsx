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
// AssessmentDetailView.tsx — one run, from progress to plan.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// The order on this page is the order the reader needs, not the order the pipeline produces:
//
//   posture -> what to do first -> per-pillar verdicts -> findings -> open questions -> provenance
//
// A report that opens with an architecture summary is a report where the reader has to scroll to
// find out whether anything is wrong. The headline and the immediate actions come first; the
// description of the software is available but below, because the person reading it already
// knows what their own tool does.
import Box from "@mui/material/Box";
import LinearProgress from "@mui/material/LinearProgress";
import Paper from "@mui/material/Paper";
import Tooltip from "@mui/material/Tooltip";
import { Banner, Button, Tag, Text } from "@nvidia/foundations-react-core";
import { Download } from "lucide-react";
import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ErrorBanner, Loading, Page, SectionHeading, WarningBanner } from "../components/Feedback";
import { FindingsTable } from "../components/FindingsTable";
import { CopyButton } from "../components/CopyButton";
import { Markdown } from "../components/Markdown";
import { SeverityTag, StatusTag, VerdictTag } from "../components/labels";
import { ProvenancePanel } from "../components/ProvenancePanel";
import { useCan } from "../context/SessionContext";
import { usePolling } from "../hooks/useApi";
import { duration, pillarLabel, shortSha, when } from "../lib/format";
import { ASSESSMENTS_PATH, pillarPath } from "../routes";
import { artifactUrl, cancelAssessment, getAssessment, retryAssessment } from "../services/factory";
import type { AssessmentDetail, Judgement, RemediationStep, Severity } from "../types/api";

const TERMINAL = ["complete", "failed", "cancelled"];

const POSTURE_TEXT: Record<string, { color: "green" | "yellow" | "red"; label: string }> = {
  "safe-to-depend-on": { color: "green", label: "Safe to depend on" },
  "needs-work-before-others-depend-on-it": {
    color: "yellow",
    label: "Needs work before others depend on it",
  },
  "do-not-deploy": { color: "red", label: "Do not deploy" },
};

export function AssessmentDetailView() {
  const { assessmentId = "" } = useParams<{ assessmentId: string }>();
  const canRetry = useCan("assessment:retry");
  const canCancel = useCan("assessment:cancel");
  const canReadProvenance = useCan("assessment:provenance");
  const [action, setAction] = useState<string | null>(null);

  const loader = useCallback(
    (signal: AbortSignal) => getAssessment(assessmentId, signal),
    [assessmentId],
  );
  const { data, loading, error, refresh } = usePolling(
    loader,
    (detail) => !detail || !TERMINAL.includes(detail.assessment.status),
    3000,
    [assessmentId],
  );

  if (loading && !data) return <Page><Loading rows={8} label="Loading assessment" /></Page>;
  if (error && !data) {
    return (
      <Page>
        <ErrorBanner message={error} />
        <Link to={ASSESSMENTS_PATH}>Back to assessments</Link>
      </Page>
    );
  }
  if (!data) return null;

  const { assessment, remediation, judgements, findings, artifacts } = data;
  const running = !TERMINAL.includes(assessment.status);

  const runControl = async (kind: "retry" | "cancel") => {
    setAction(kind);
    try {
      await (kind === "retry" ? retryAssessment(assessmentId) : cancelAssessment(assessmentId));
      refresh();
    } catch (caught) {
      setAction(null);
      throw caught;
    }
    setAction(null);
  };

  return (
    <Page>
      <SectionHeading
        title="Assessment"
        detail={
          <>
            <StatusTag status={assessment.status} />{" "}
            {assessment.ref ? `${assessment.ref} · ` : ""}
            <span className="nvsf-code">{shortSha(assessment.commit_sha)}</span>
            {" · started "}
            <Tooltip title={when(assessment.created_at).absolute}>
              <span>{when(assessment.created_at).relative}</span>
            </Tooltip>
            {" · "}
            {duration(assessment.started_at, assessment.finished_at)}
            {assessment.standards_version ? ` · baseline ${assessment.standards_version}` : ""}
          </>
        }
        action={
          <Box sx={{ display: "flex", gap: 1 }}>
            {running && canCancel && (
              <Button kind="secondary" size="small" onClick={() => void runControl("cancel")} disabled={action !== null}>
                Cancel
              </Button>
            )}
            {assessment.status === "failed" && assessment.failure?.retryable && canRetry && (
              <Button kind="primary" size="small" onClick={() => void runControl("retry")} disabled={action !== null}>
                Retry
              </Button>
            )}
          </Box>
        }
      />

      {running && <ProgressPanel detail={data} />}

      {assessment.status === "failed" && assessment.failure && (
        <Box sx={{ mb: 3 }}>
          <Banner status="error">
            <Text kind="body/bold/sm" style={{ display: "block" }}>
              {assessment.failure.reason}
            </Text>
            <Text kind="body/regular/sm">{assessment.failure.detail}</Text>
            <Text kind="body/regular/sm" style={{ display: "block", marginTop: 8 }}>
              {assessment.failure.retryable
                ? "Retryable. A retry resumes from the last completed reasoning pass rather than starting over."
                : "Not retryable — retrying would fail the same way. Fix the cause named above first."}
            </Text>
          </Banner>
        </Box>
      )}

      {assessment.status === "cancelled" && (
        <WarningBanner>
          This run was cancelled, so anything below is partial. Start a new run for a complete
          picture.
        </WarningBanner>
      )}

      {/* ── The answer, first ─────────────────────────────────────────────────────────── */}
      {remediation && (
        <Paper variant="outlined" sx={{ p: 3, mb: 4 }}>
          <Box sx={{ display: "flex", gap: 2, alignItems: "flex-start", flexWrap: "wrap" }}>
            {remediation.posture && POSTURE_TEXT[remediation.posture] && (
              <Tag
                color={POSTURE_TEXT[remediation.posture].color}
                kind="solid"
                readOnly
                density="compact"
              >
                {POSTURE_TEXT[remediation.posture].label}
              </Tag>
            )}
            <Box sx={{ flexGrow: 1, minWidth: 260 }}>
              <Text kind="body/bold/md" style={{ display: "block" }}>
                {remediation.headline ?? "No headline was produced."}
              </Text>
              {remediation.posture_reason && (
                <Text
                  kind="body/regular/sm"
                  style={{ color: "var(--text-color-secondary)", display: "block", marginTop: 4 }}
                >
                  {remediation.posture_reason}
                </Text>
              )}
            </Box>
            <SeverityCounts counts={data.severity_counts} />
          </Box>
        </Paper>
      )}

      {/* ── The deliverable ───────────────────────────────────────────────────────────── */}
      {artifacts.length > 0 && (
        <Paper variant="outlined" sx={{ p: 3, mb: 4 }}>
          <Text kind="body/bold/md" style={{ display: "block", marginBottom: 4 }}>
            Documents
          </Text>
          <Text
            kind="body/regular/sm"
            style={{ color: "var(--text-color-secondary)", display: "block", marginBottom: 12 }}
          >
            AGENT_PLAN.md is the one to hand to a coding agent. ASSESSMENT.md is for a human
            reviewer, and EVIDENCE.md is what the model was given — read it if you disagree with a
            conclusion.
          </Text>
          <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
            {artifacts.map((artifact) => (
              <Button key={artifact.filename} kind="secondary" size="small" asChild>
                <a href={artifactUrl(assessmentId, artifact.filename)}>
                  <Download size={14} />
                  {artifact.filename}
                </a>
              </Button>
            ))}
          </Box>
        </Paper>
      )}

      {remediation?.agent_preamble && (
        <Paper variant="outlined" sx={{ p: 3, mb: 4 }}>
          <Box
            sx={{ display: "flex", justifyContent: "space-between", gap: 2, alignItems: "center", mb: 1 }}
          >
            <Text kind="body/bold/md">Paste this at the top of your agent session</Text>
            <CopyButton text={remediation.agent_preamble} label="Copy preamble" />
          </Box>
          <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
            It tells the agent what this repository is, what matters about it, and the constraints
            to respect while changing it — the context an agent otherwise guesses at.
          </Text>
          <Box sx={{ mt: 2, p: 2, bgcolor: "action.hover", borderRadius: 1 }}>
            <span className="nvsf-code">{remediation.agent_preamble}</span>
          </Box>
        </Paper>
      )}

      {remediation && <RemediationPlan remediation={remediation} />}

      {/* ── Per-pillar verdicts ───────────────────────────────────────────────────────── */}
      {Object.keys(judgements).length > 0 && (
        <Box sx={{ mb: 4 }}>
          <SectionHeading
            title="Per-pillar verdicts"
            detail="Each pillar is judged separately, and each criterion says whether it was measured or reasoned about."
          />
          <Box sx={{ display: "grid", gap: 2 }}>
            {Object.entries(judgements).map(([pillarId, judgement]) => (
              <PillarJudgement key={pillarId} pillarId={pillarId} judgement={judgement} />
            ))}
          </Box>
        </Box>
      )}

      {/* ── Findings ──────────────────────────────────────────────────────────────────── */}
      <Box sx={{ mb: 4 }}>
        <SectionHeading
          title={`Findings (${findings.length})`}
          detail="A scanner finding is a measurement. A model finding is a judgement. An escalation is a measurement the model argued was worse in context — and a scanner's severity is a floor that can never be lowered."
        />
        <FindingsTable findings={findings} />
      </Box>

      {/* ── Open questions ────────────────────────────────────────────────────────────── */}
      {data.open_questions && <OpenQuestionsPanel questions={data.open_questions} />}

      {/* ── Architecture ──────────────────────────────────────────────────────────────── */}
      {data.architecture && <ArchitecturePanel architecture={data.architecture} />}

      {/* ── Provenance ────────────────────────────────────────────────────────────────── */}
      {canReadProvenance && <ProvenancePanel assessmentId={assessmentId} />}
    </Page>
  );
}

/**
 * Progress as a stage name and a pass count.
 *
 * No percentage, deliberately: the backend does not invent one and neither does this. An invented
 * percentage that sits at 80% for four minutes is worse than "judging Scalability (4 of 8)",
 * which tells the reader what is happening and roughly how much is left.
 */
function ProgressPanel({ detail }: { detail: AssessmentDetail }) {
  const { progress } = detail;
  return (
    <Paper variant="outlined" sx={{ p: 3, mb: 4 }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", gap: 2, mb: 1 }}>
        <Text kind="body/bold/sm">{progress.stage}</Text>
        {progress.passes_total > 0 && (
          <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
            reasoning pass {progress.passes_done} of {progress.passes_total}
          </Text>
        )}
      </Box>
      {progress.detail && (
        <Text
          kind="body/regular/sm"
          style={{ color: "var(--text-color-secondary)", display: "block", marginBottom: 8 }}
        >
          {progress.detail}
        </Text>
      )}
      <LinearProgress
        variant={progress.passes_total > 0 ? "determinate" : "indeterminate"}
        value={
          progress.passes_total > 0
            ? (progress.passes_done / progress.passes_total) * 100
            : undefined
        }
      />
    </Paper>
  );
}

function SeverityCounts({ counts }: { counts: Record<Severity, number> }) {
  const severities: Severity[] = ["blocker", "major", "minor", "info"];
  const any = severities.some((severity) => counts[severity] > 0);
  if (!any) return null;
  return (
    <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
      {severities
        .filter((severity) => counts[severity] > 0)
        .map((severity) => (
          <SeverityTag key={severity} severity={severity} count={counts[severity]} />
        ))}
    </Box>
  );
}

function Step({ step }: { step: RemediationStep }) {
  return (
    <Box sx={{ borderBottom: 1, borderColor: "divider", py: 2 }}>
      <Box sx={{ display: "flex", gap: 1, alignItems: "baseline", flexWrap: "wrap" }}>
        <Text kind="body/bold/sm">{step.title}</Text>
        {step.effort && (
          <Tag color="gray" kind="outline" readOnly density="compact">
            {step.effort}
          </Tag>
        )}
      </Box>
      {step.why && (
        <Text kind="body/regular/sm" style={{ display: "block", marginTop: 4 }}>
          {step.why}
        </Text>
      )}
      {step.where && (
        <Text
          kind="body/regular/xs"
          style={{ color: "var(--text-color-secondary)", display: "block", marginTop: 4 }}
        >
          <span className="nvsf-code">{step.where}</span>
        </Text>
      )}
      {step.what_to_do && (
        <Box sx={{ mt: 1 }}>
          <Markdown source={step.what_to_do} />
        </Box>
      )}
      {/* How the author confirms the fix worked. Without it a remediation item is advice; with it
          it is a task with a definition of done. */}
      {step.verify && (
        <Box sx={{ mt: 1, pl: 2, borderLeft: 3, borderColor: "primary.main" }}>
          <Text kind="body/regular/xs" style={{ color: "var(--text-color-secondary)", display: "block" }}>
            Verify
          </Text>
          <Text kind="body/regular/sm">{step.verify}</Text>
        </Box>
      )}
    </Box>
  );
}

function RemediationPlan({ remediation }: { remediation: NonNullable<AssessmentDetail["remediation"]> }) {
  const groups: [string, string, RemediationStep[] | undefined][] = [
    ["Do first", "Before anyone else depends on this.", remediation.immediate],
    ["Do next", "Once the immediate items are done.", remediation.next],
    ["Later", "Worth doing, not urgent.", remediation.later],
  ];

  return (
    <Box sx={{ mb: 4 }}>
      <SectionHeading title="Remediation plan" />
      {groups.map(([title, blurb, steps]) =>
        steps?.length ? (
          <Paper key={title} variant="outlined" sx={{ p: 3, mb: 2 }}>
            <Text kind="body/bold/md" style={{ display: "block" }}>
              {title}
            </Text>
            <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
              {blurb}
            </Text>
            {steps.map((step, index) => (
              <Step key={index} step={step} />
            ))}
          </Paper>
        ) : null,
      )}

      {/* The most valuable section for an agent, and the one a generic best-practices list can
          never produce: plausible changes that would be wrong for THIS repository. */}
      {remediation.do_not_do?.length ? (
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Text kind="body/bold/md" style={{ display: "block", marginBottom: 8 }}>
            Do not do these
          </Text>
          {remediation.do_not_do.map((entry, index) => (
            <Box key={index} sx={{ mb: 1.5 }}>
              <Text kind="body/bold/sm" style={{ display: "block" }}>
                {entry.suggestion}
              </Text>
              <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
                {entry.why_not}
              </Text>
            </Box>
          ))}
        </Paper>
      ) : null}
    </Box>
  );
}

function PillarJudgement({ pillarId, judgement }: { pillarId: string; judgement: Judgement }) {
  const [open, setOpen] = useState(false);
  const outcomes = judgement.criteria ?? [];
  const failed = outcomes.filter((criterion) => criterion.outcome === "fail").length;

  return (
    <Paper variant="outlined" sx={{ p: 2.5 }}>
      <Box
        sx={{ display: "flex", gap: 2, alignItems: "center", flexWrap: "wrap", cursor: "pointer" }}
        onClick={() => setOpen((value) => !value)}
      >
        <VerdictTag verdict={judgement.verdict} />
        <Text kind="body/bold/sm" style={{ flexGrow: 1 }}>
          {pillarLabel(pillarId)}
        </Text>
        {outcomes.length > 0 && (
          <Text kind="body/regular/xs" style={{ color: "var(--text-color-secondary)" }}>
            {failed} of {outcomes.length} criteria failing
          </Text>
        )}
        <Link to={pillarPath(pillarId)} onClick={(event) => event.stopPropagation()}>
          <Text kind="body/regular/xs">what good looks like</Text>
        </Link>
      </Box>

      {judgement.summary && (
        <Text kind="body/regular/sm" style={{ display: "block", marginTop: 8 }}>
          {judgement.summary}
        </Text>
      )}

      <CriteriaDetail open={open} outcomes={outcomes} judgement={judgement} />
    </Paper>
  );
}

function CriteriaDetail({
  open,
  outcomes,
  judgement,
}: {
  open: boolean;
  outcomes: NonNullable<Judgement["criteria"]>;
  judgement: Judgement;
}) {
  if (!open) return null;
  return (
    <Box sx={{ mt: 2, display: "grid", gap: 1.5 }}>
      {outcomes.map((criterion, index) => (
        <Box key={index} sx={{ pl: 2, borderLeft: 2, borderColor: "divider" }}>
          <Text kind="body/bold/xs" style={{ display: "block" }}>
            {criterion.id} — {criterion.outcome}
          </Text>
          <Text kind="body/regular/sm">{criterion.reasoning}</Text>
          {criterion.evidence && (
            <Text
              kind="body/regular/xs"
              style={{ color: "var(--text-color-secondary)", display: "block" }}
            >
              <span className="nvsf-code">{criterion.evidence}</span>
            </Text>
          )}
        </Box>
      ))}

      {/* The model's own doubts about the scanners. Surfaced rather than hidden: a scanner that
          is wrong about a repository should be findable, and this is the record of the model
          saying so. It does not remove the finding -- the ratchet forbids that -- it annotates it. */}
      {judgement.suspected_false_positives?.length ? (
        <Box sx={{ mt: 1 }}>
          <Text kind="body/bold/xs" style={{ display: "block" }}>
            The model thinks these findings may be wrong
          </Text>
          {judgement.suspected_false_positives.map((entry, index) => (
            <Text key={index} kind="body/regular/sm" style={{ display: "block" }}>
              {entry.finding_title}: {entry.why}
            </Text>
          ))}
        </Box>
      ) : null}
    </Box>
  );
}

function OpenQuestionsPanel({
  questions,
}: {
  questions: NonNullable<AssessmentDetail["open_questions"]>;
}) {
  const list = questions.questions ?? [];
  const assumptions = questions.assumptions_made ?? [];
  if (!list.length && !assumptions.length) return null;

  return (
    <Box sx={{ mb: 4 }}>
      <SectionHeading
        title="Open questions"
        detail="Answers that would change this assessment. Where a question went unanswered, the assumption made in its place is recorded below."
      />
      {list.length > 0 && (
        <Paper variant="outlined" sx={{ p: 3, mb: 2 }}>
          {list.map((entry, index) => (
            <Box key={index} sx={{ mb: 2 }}>
              <Text kind="body/bold/sm" style={{ display: "block" }}>
                {entry.question}
              </Text>
              <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
                {entry.why_it_matters}
              </Text>
              <Box sx={{ mt: 0.5, display: "grid", gap: 0.25 }}>
                {entry.if_yes && <Text kind="body/regular/xs">If yes: {entry.if_yes}</Text>}
                {entry.if_no && <Text kind="body/regular/xs">If no: {entry.if_no}</Text>}
              </Box>
            </Box>
          ))}
        </Paper>
      )}
      {assumptions.length > 0 && (
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Text kind="body/bold/md" style={{ display: "block", marginBottom: 8 }}>
            Assumptions this assessment made
          </Text>
          {assumptions.map((entry, index) => (
            <Box key={index} sx={{ mb: 1.5 }}>
              <Text kind="body/bold/sm" style={{ display: "block" }}>
                {entry.assumption}
              </Text>
              <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
                {entry.chosen_because}
              </Text>
              {entry.if_wrong && (
                <Text kind="body/regular/xs" style={{ display: "block" }}>
                  If wrong: {entry.if_wrong}
                </Text>
              )}
            </Box>
          ))}
        </Paper>
      )}
    </Box>
  );
}

function ArchitecturePanel({
  architecture,
}: {
  architecture: NonNullable<AssessmentDetail["architecture"]>;
}) {
  return (
    <Box sx={{ mb: 4 }}>
      <SectionHeading
        title="What this software is"
        detail="Described from the evidence alone, before anything was judged. If this disagrees with what you expected, the disagreement is itself a finding."
      />
      <Paper variant="outlined" sx={{ p: 3 }}>
        {architecture.purpose && <Text kind="body/regular/sm">{architecture.purpose}</Text>}

        <Box sx={{ display: "grid", gap: 2, mt: 2 }}>
          {architecture.archetype && (
            <Field label="Archetype" value={architecture.archetype} />
          )}
          {architecture.who_depends_on_it && (
            <Field label="Who depends on it" value={architecture.who_depends_on_it} />
          )}
          {architecture.state && (
            <Field
              label="State that would matter if lost"
              value={`${architecture.state.what_state_exists ?? "—"} — lives in: ${
                architecture.state.where_it_lives ?? "undetermined"
              }`}
              evidence={architecture.state.evidence}
            />
          )}
          {architecture.external_dependencies?.length ? (
            <Field
              label="External dependencies"
              value={architecture.external_dependencies
                .map((dependency) => `${dependency.what} (${dependency.how})`)
                .join(", ")}
            />
          ) : null}
        </Box>

        {/* What the evidence could not settle. Published rather than omitted: a report that lists
            its own blind spots is one a reader can calibrate, and the alternative is a confident
            statement about something the scanners never saw. */}
        {architecture.not_determinable?.length ? (
          <Box sx={{ mt: 3, pt: 2, borderTop: 1, borderColor: "divider" }}>
            <Text kind="body/bold/sm" style={{ display: "block" }}>
              What this evidence could not answer
            </Text>
            <ul>
              {architecture.not_determinable.map((item, index) => (
                <li key={index}>
                  <Text kind="body/regular/sm">{item}</Text>
                </li>
              ))}
            </ul>
          </Box>
        ) : null}
      </Paper>
    </Box>
  );
}

function Field({
  label,
  value,
  evidence,
}: {
  label: string;
  value: string;
  evidence?: string;
}) {
  return (
    <Box>
      <Text
        kind="body/regular/xs"
        style={{ color: "var(--text-color-secondary)", display: "block" }}
      >
        {label}
      </Text>
      <Text kind="body/regular/sm">{value}</Text>
      {evidence && (
        <Text kind="body/regular/xs" style={{ display: "block" }}>
          <span className="nvsf-code">{evidence}</span>
        </Text>
      )}
    </Box>
  );
}
