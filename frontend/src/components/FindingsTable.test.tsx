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
// FindingsTable.test.tsx — the report must not blur measurement and judgement.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// The ratchet in the backend is what keeps the model from downgrading a measured fact. These
// tests cover the other half of that guarantee: the UI has to *show* which is which, or the
// distinction the pipeline works to preserve is invisible to the reader.
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "../test/render";
import type { Finding } from "../types/api";
import { FindingsTable } from "./FindingsTable";

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: "f1",
    pillar_id: "durability",
    criterion: "D1",
    title: "State is held only in memory",
    detail: "The container writes nothing to a mounted path.",
    severity: "blocker",
    origin: "scanner",
    escalated_from: null,
    detector: "in-memory-state",
    file_path: "app/store.py",
    line_start: 42,
    line_end: 48,
    citation: "CACHE = {}",
    remediation: "Persist to a bind-mounted SQLite database.",
    ...overrides,
  };
}

describe("provenance of each finding", () => {
  it("labels a scanner finding as a measurement", () => {
    renderWithProviders(<FindingsTable findings={[finding()]} />);
    expect(screen.getByText("scanner")).toBeInTheDocument();
  });

  it("labels a model finding distinctly from a scanner finding", () => {
    renderWithProviders(
      <FindingsTable findings={[finding({ origin: "model", detector: null })]} />,
    );
    expect(screen.getByText("model")).toBeInTheDocument();
    expect(screen.queryByText("scanner")).toBeNull();
  });

  it("says what an escalated finding was escalated from", () => {
    // Without the original severity the reader cannot tell whether the model nudged a minor to a
    // major or jumped it to a blocker, and those warrant very different responses.
    renderWithProviders(
      <FindingsTable
        findings={[finding({ origin: "escalated", severity: "blocker", escalated_from: "minor" })]}
      />,
    );
    expect(screen.getByText("escalated from minor")).toBeInTheDocument();
  });
});

describe("grouping and ordering", () => {
  it("puts blockers first regardless of the order they arrive in", () => {
    const { container } = renderWithProviders(
      <FindingsTable
        findings={[
          finding({ id: "a", severity: "info", title: "An observation" }),
          finding({ id: "b", severity: "blocker", title: "Data loss on restart" }),
          finding({ id: "c", severity: "minor", title: "A nit" }),
        ]}
      />,
    );

    const text = container.textContent ?? "";
    expect(text.indexOf("Data loss on restart")).toBeLessThan(text.indexOf("A nit"));
    expect(text.indexOf("A nit")).toBeLessThan(text.indexOf("An observation"));
  });

  it("counts each severity group", () => {
    renderWithProviders(
      <FindingsTable
        findings={[
          finding({ id: "a", severity: "major" }),
          finding({ id: "b", severity: "major" }),
        ]}
      />,
    );
    expect(screen.getByText("2 major")).toBeInTheDocument();
  });
});

describe("evidence", () => {
  it("opens a blocker expanded, because it is the thing to read first", () => {
    renderWithProviders(<FindingsTable findings={[finding()]} />);

    expect(screen.getByText("app/store.py:42-48")).toBeVisible();
    expect(screen.getByText("Persist to a bind-mounted SQLite database.")).toBeVisible();
  });

  it("shows a citation so a conclusion can be checked against the source", () => {
    renderWithProviders(<FindingsTable findings={[finding()]} />);
    expect(screen.getByText("CACHE = {}")).toBeInTheDocument();
  });

  it("renders a finding with no file, because a model finding may have none", () => {
    renderWithProviders(
      <FindingsTable
        findings={[
          finding({
            origin: "model",
            file_path: null,
            line_start: null,
            line_end: null,
            citation: null,
            detector: null,
          }),
        ]}
      />,
    );
    expect(screen.getByText("State is held only in memory")).toBeInTheDocument();
  });
});

describe("no findings", () => {
  it("says the checks ran rather than showing a blank panel", () => {
    // An empty page reads as a failure. "No findings" is a result, and has to look like one.
    renderWithProviders(<FindingsTable findings={[]} />);
    expect(screen.getByText(/No findings\./)).toBeInTheDocument();
    expect(screen.getByText(/the scanners ran and the model judged every pillar/)).toBeInTheDocument();
  });
});
