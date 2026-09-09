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
// ValidateView.test.tsx — the one page in the contract section with no model in it.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "../test/render";
import { ValidateView } from "./ValidateView";

const INDEX = {
  ok: true,
  nrm_version: "v0.1",
  entities: [
    { name: "resource", title: "Resource", schema: "resource.schema.json", summary: "An instance." },
    { name: "link", title: "Link", schema: "link.schema.json", summary: "A connection." },
  ],
  supporting: [],
  links: {
    bundle: "/api/contracts/bundle",
    agent_pack: "/api/contracts/agent-pack.md",
    crosswalks: "/api/contracts/crosswalk",
    validate: "/api/contracts/validate",
    openapi: "/api/openapi.json",
    schema_base: "/api/contracts/nrm/v0.1",
  },
};

function stub(result: unknown, status = 200) {
  return vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/validate")) return Promise.resolve(Response.json(result, { status }));
    return Promise.resolve(Response.json(INDEX));
  });
}

async function validate(payload = '{"nrm_version": "v0.1"}') {
  const user = userEvent.setup();
  renderWithProviders(<ValidateView />);
  await user.click(await screen.findByLabelText(/Your export/));
  await user.paste(payload);
  await user.click(screen.getByRole("button", { name: "Validate" }));
  return user;
}

describe("the verdict", () => {
  it("says conformant, and says what that entitles the caller to do", async () => {
    vi.stubGlobal(
      "fetch",
      stub({
        ok: true,
        valid: true,
        mode: "bundle",
        nrm_version: "v0.1",
        problem_count: 0,
        problems: [],
        counts: { resources: 3, links: 2 },
      }),
    );
    await validate();

    await waitFor(() => expect(screen.getByText("Conformant.")).toBeInTheDocument());
    expect(screen.getByText(/can be handed to any NVIS tool/)).toBeInTheDocument();
    // What was actually checked, so "valid" cannot be read off an empty document.
    expect(screen.getByText("3 resources")).toBeInTheDocument();
  });

  it("locates each problem by JSON Pointer and names the rule", async () => {
    // A message alone means searching the document. The pointer is what makes the answer
    // actionable on a bundle with hundreds of records.
    vi.stubGlobal(
      "fetch",
      stub({
        ok: true,
        valid: false,
        mode: "bundle",
        nrm_version: "v0.1",
        problem_count: 2,
        problems: [
          {
            pointer: "/links/0/a_port_id",
            message: "references a port that is not in this bundle",
            rule: "reference.dangling",
          },
          {
            pointer: "/resources/4/parent_id",
            message: "containment cycle: resources/4 contains itself",
            rule: "invariant.containment_acyclic",
          },
        ],
      }),
    );
    await validate();

    await waitFor(() => expect(screen.getByText("2 problems.")).toBeInTheDocument());
    expect(screen.getByText("/links/0/a_port_id")).toBeInTheDocument();
    expect(screen.getByText("invariant.containment_acyclic")).toBeInTheDocument();
  });

  it("warns when a check could not run, so a pass is not read as more than it is", async () => {
    // Validating a single record cannot check references. A bare "valid" there would be the most
    // misleading answer this endpoint could give.
    vi.stubGlobal(
      "fetch",
      stub({
        ok: true,
        valid: true,
        mode: "record",
        nrm_version: "v0.1",
        problem_count: 0,
        problems: [],
        not_checked: ["reference resolution needs the whole bundle"],
      }),
    );
    await validate();

    await waitFor(() =>
      expect(screen.getByText(/Not checked: reference resolution needs the whole bundle/)).toBeInTheDocument(),
    );
  });
});

describe("the request", () => {
  it("reports a JSON syntax error locally, with the parser's own message", async () => {
    const fetchMock = stub({ ok: true, valid: true, problem_count: 0, problems: [] });
    vi.stubGlobal("fetch", fetchMock);
    await validate('{"nrm_version": "v0.1",}');

    await waitFor(() => expect(screen.getByText(/That is not valid JSON/)).toBeInTheDocument());
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/validate"))).toHaveLength(0);
  });

  it("validates a bundle by default, and a single record only when asked", async () => {
    const fetchMock = stub({ ok: true, valid: true, problem_count: 0, problems: [] });
    vi.stubGlobal("fetch", fetchMock);
    const user = await validate();

    const bodies = () =>
      fetchMock.mock.calls
        .filter(([url]) => String(url) === "/api/contracts/validate")
        .map(([, init]) => JSON.parse(String(init?.body)) as Record<string, unknown>);

    // Default: the payload goes up as-is, because a bundle is already the request shape.
    await waitFor(() => expect(bodies()).toHaveLength(1));
    expect(bodies()[0]).toEqual({ nrm_version: "v0.1" });

    await user.click(screen.getByRole("combobox", { name: /Mode/ }));
    await user.click(await screen.findByRole("option", { name: /One Resource record/ }));
    await user.click(screen.getByRole("button", { name: "Validate" }));

    // Record mode: wrapped, so the endpoint knows which schema to adjudicate against and can
    // report the cross-record checks it therefore cannot run.
    await waitFor(() => expect(bodies()).toHaveLength(2));
    expect(bodies()[1]).toEqual({ entity: "resource", record: { nrm_version: "v0.1" } });
  });

  it("says nothing is sent to a model and nothing is stored", async () => {
    // The reason a team is willing to paste a real inventory export into this box.
    vi.stubGlobal("fetch", stub({ ok: true, valid: true, problem_count: 0, problems: [] }));
    renderWithProviders(<ValidateView />);

    expect(
      await screen.findByText(/Nothing here is sent to a language model, and nothing is stored/),
    ).toBeInTheDocument();
  });
});
