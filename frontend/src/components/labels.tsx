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
// labels.tsx — every status badge in the app, and the colour it maps to.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// One file for all of them so the same concept never gets two colours. A "failed" run rendered
// red on one page and grey on another makes a reader doubt both.
import Tooltip from "@mui/material/Tooltip";
import { Tag } from "@nvidia/foundations-react-core";

import type { AssessmentStatus, Detector, FindingOrigin, Severity, Verdict } from "../types/api";

type TagColor = "green" | "red" | "yellow" | "blue" | "gray" | "purple" | "teal";

const SEVERITY_COLOR: Record<Severity, TagColor> = {
  blocker: "red",
  major: "yellow",
  minor: "blue",
  info: "gray",
};

const STATUS_COLOR: Record<AssessmentStatus, TagColor> = {
  queued: "gray",
  acquiring: "blue",
  scanning: "blue",
  reasoning: "purple",
  rendering: "blue",
  complete: "green",
  failed: "red",
  cancelled: "gray",
};

const VERDICT_COLOR: Record<Verdict, TagColor> = {
  pass: "green",
  concerns: "yellow",
  fail: "red",
  undetermined: "gray",
};

const SEVERITY_MEANING: Record<Severity, string> = {
  blocker: "Someone will lose data, leak data, or be unable to recover. Fix before anyone depends on this.",
  major: "Will cause a real incident under normal conditions.",
  minor: "Worth fixing, but nothing breaks today.",
  info: "An observation, not a defect.",
};

export function SeverityTag({ severity, count }: { severity: Severity; count?: number }) {
  return (
    <Tooltip title={SEVERITY_MEANING[severity]}>
      <span>
        <Tag color={SEVERITY_COLOR[severity]} kind="solid" readOnly density="compact">
          {count === undefined ? severity : `${count} ${severity}`}
        </Tag>
      </span>
    </Tooltip>
  );
}

export function StatusTag({ status }: { status: AssessmentStatus }) {
  return (
    <Tag color={STATUS_COLOR[status]} kind="solid" readOnly density="compact">
      {status}
    </Tag>
  );
}

export function VerdictTag({ verdict }: { verdict: Verdict | undefined }) {
  const resolved: Verdict = verdict ?? "undetermined";
  return (
    <Tag color={VERDICT_COLOR[resolved]} kind="solid" readOnly density="compact">
      {resolved}
    </Tag>
  );
}

/**
 * Where a finding came from.
 *
 * The most important badge in the application. A scanner finding is a measurement; a model
 * finding is an opinion; an escalation is a measurement the model argued was worse than the
 * scanner could tell. A reader who cannot distinguish them has no basis for deciding how much
 * of the report to act on, and the ratchet that produces this distinction is worth nothing if
 * the UI then hides it.
 */
export function OriginTag({
  origin,
  escalatedFrom,
}: {
  origin: FindingOrigin;
  escalatedFrom?: Severity | null;
}) {
  if (origin === "scanner") {
    return (
      <Tooltip title="Found by a deterministic scanner. This is a measurement, not a judgement.">
        <span>
          <Tag color="teal" kind="outline" readOnly density="compact">
            scanner
          </Tag>
        </span>
      </Tooltip>
    );
  }
  if (origin === "escalated") {
    return (
      <Tooltip
        title={
          escalatedFrom
            ? `A scanner reported this as ${escalatedFrom}; the model argued it is worse in this ` +
              `repository's context. The scanner's severity is the floor -- it can never be lowered.`
            : "Severity raised by the model above what the scanner reported."
        }
      >
        <span>
          <Tag color="purple" kind="solid" readOnly density="compact">
            escalated{escalatedFrom ? ` from ${escalatedFrom}` : ""}
          </Tag>
        </span>
      </Tooltip>
    );
  }
  return (
    <Tooltip title="Raised by the model, with no deterministic detector behind it. Judgement, not measurement.">
      <span>
        <Tag color="purple" kind="outline" readOnly density="compact">
          model
        </Tag>
      </span>
    </Tooltip>
  );
}

/** Whether a criterion is checkable by a scanner or is a judgement call. */
export function DetectorTag({ detector }: { detector: Detector }) {
  const map: Record<Detector, { color: TagColor; label: string; help: string }> = {
    yes: {
      color: "teal",
      label: "measured",
      help: "A scanner checks this. The model confirms a fact rather than forming an opinion.",
    },
    partial: {
      color: "blue",
      label: "partly measured",
      help: "A scanner covers part of this criterion; the rest is judgement.",
    },
    no: {
      color: "gray",
      label: "judgement",
      help: "No detector exists. This is the model reasoning from evidence, and should be read as such.",
    },
  };
  const { color, label, help } = map[detector];
  return (
    <Tooltip title={help}>
      <span>
        <Tag color={color} kind="outline" readOnly density="compact">
          {label}
        </Tag>
      </span>
    </Tooltip>
  );
}

/** Crosswalk role: which direction data is allowed to flow. */
export function RoleTag({ role }: { role: string }) {
  const color: TagColor =
    role === "source_of_record" ? "green" : role === "export_target" ? "blue" : "gray";
  return (
    <Tag color={color} kind="outline" readOnly density="compact">
      {role.replace(/_/g, " ")}
    </Tag>
  );
}
