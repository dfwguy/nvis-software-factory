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
// StartAssessmentPanel.test.tsx — starting a run, including when it cannot be started.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "../test/render";
import { StartAssessmentPanel } from "./StartAssessmentPanel";

const URL = "https://gitlab-master.nvidia.com/nvis/some-tool";

function stub(response: unknown, status = 200) {
  return vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
    Promise.resolve(Response.json(response, { status })),
  );
}

async function start(onStarted = vi.fn()) {
  const user = userEvent.setup();
  renderWithProviders(<StartAssessmentPanel onStarted={onStarted} />);
  await user.type(screen.getByLabelText("Repository URL"), URL);
  await user.click(screen.getByRole("button", { name: "Start assessment" }));
  return { user, onStarted };
}

describe("starting a run", () => {
  it("hands the new run's id to the caller so it can navigate", async () => {
    vi.stubGlobal("fetch", stub({ ok: true, assessment: { id: "run-1" } }));
    const { onStarted } = await start();

    await waitFor(() => expect(onStarted).toHaveBeenCalledWith("run-1"));
  });

  it("sends the optional context only when it was filled in", async () => {
    // An empty string and an unanswered question are different inputs to the model: one says
    // "nobody depends on this", the other says "unknown".
    const fetchMock = stub({ ok: true, assessment: { id: "run-2" } });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderWithProviders(<StartAssessmentPanel onStarted={vi.fn()} />);

    await user.type(screen.getByLabelText("Repository URL"), URL);
    await user.click(screen.getByText(/Add context/));
    await user.type(screen.getByLabelText("What is it for?"), "Collects DCGM health");
    await user.click(screen.getByRole("button", { name: "Start assessment" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.purpose).toBe("Collects DCGM health");
    expect(body).not.toHaveProperty("criticality");
    expect(body).not.toHaveProperty("data_handled");
  });

  it("will not submit without a URL", async () => {
    vi.stubGlobal("fetch", stub({ ok: true }));
    renderWithProviders(<StartAssessmentPanel onStarted={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Start assessment" })).toBeDisabled();
  });

  it("does not ask for a URL when started from a repository's own page", async () => {
    vi.stubGlobal("fetch", stub({ ok: true, assessment: { id: "run-3" } }));
    renderWithProviders(
      <StartAssessmentPanel onStarted={vi.fn()} repositoryId="repo-1" repositoryLabel="nvis/tool" />,
    );

    expect(screen.queryByLabelText("Repository URL")).toBeNull();
    expect(screen.getByText("Assess nvis/tool")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start assessment" })).toBeEnabled();
  });
});

describe("when a run cannot start", () => {
  it("says the reasoning endpoint is down rather than blaming the input", async () => {
    // Reasoning is a required stage, so this is not a validation error and there is nothing for
    // the user to correct. A red box beside the URL field would send them looking for a typo.
    vi.stubGlobal(
      "fetch",
      stub(
        {
          ok: false,
          error: "the reasoning endpoint is unreachable, so no assessment can run right now.",
          reason: "llm-unavailable",
        },
        503,
      ),
    );
    const { onStarted } = await start();

    await waitFor(() =>
      expect(screen.getByText(/the reasoning endpoint is unreachable/)).toBeInTheDocument(),
    );
    expect(onStarted).not.toHaveBeenCalled();
  });

  it("points at the run already in flight instead of starting a second one", async () => {
    vi.stubGlobal(
      "fetch",
      stub(
        {
          ok: false,
          error: "an assessment is already running",
          reason: "already-running",
          assessment_id: "run-9",
        },
        409,
      ),
    );
    await start();

    await waitFor(() => expect(screen.getByText(/already running/)).toBeInTheDocument());
    expect(screen.getByText(/Assessments list/)).toBeInTheDocument();
  });

  it("re-enables the button after a failure, so the user can try again", async () => {
    vi.stubGlobal("fetch", stub({ ok: false, error: "that host is not allowed" }, 400));
    await start();

    await waitFor(() => expect(screen.getByText("that host is not allowed")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Start assessment" })).toBeEnabled();
  });
});

describe("what the panel promises about the clone", () => {
  it("states that nothing is executed and credentials are redacted first", async () => {
    // The two questions every SA asks before pasting an internal repository URL into a tool.
    vi.stubGlobal("fetch", stub({ ok: true }));
    renderWithProviders(<StartAssessmentPanel onStarted={vi.fn()} />);

    expect(screen.getByText(/Nothing from the repository is executed/)).toBeInTheDocument();
    expect(screen.getByText(/credential-shaped is replaced/)).toBeInTheDocument();
  });
});
