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
// MappingAssistantView.test.tsx — the schema has the last word, and the UI has to say so.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// This view is where a model touches the contract. The tests below are the guarantees that make
// that acceptable: the verdict is what the reader sees first, model confidence is visibly
// discounted, and an unreachable model produces no plausible-looking guess.
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "../test/render";
import { MappingAssistantView } from "./MappingAssistantView";

const INDEX = {
  ok: true,
  nrm_version: "v0.1",
  entities: [
    { name: "resource", title: "Resource", schema: "resource.schema.json", summary: "An instance." },
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

const COVERAGE = {
  ok: true,
  nrm_version: "v0.1",
  systems: {
    nautobot: {
      role: "source_of_record",
      entities: {},
      missing_entities: [],
    },
  },
};

function proposal(overrides: Record<string, unknown> = {}) {
  return {
    ok: true,
    entity: "resource",
    nrm_version: "v0.1",
    field_map: [
      {
        source_field: "serial_no",
        nrm_field: "identifiers[]",
        transform: "to_serial_identifier",
        reasoning: "A serial is an identifier, not a name.",
      },
    ],
    identifiers: [],
    record: { id: "x", resource_type_id: "y" },
    unmapped_source_fields: [{ field: "state", why: "NRM models lifecycle, not provisioning state" }],
    unfilled_required_fields: [],
    model_confidence: "high",
    model_confidence_reason: "The field names were unambiguous.",
    adjudication: { valid: true, problem_count: 0, problems: [] },
    provenance: { model: "test-model", prompt_version: "1.0.0", temperature: 0 },
    note: "jsonschema decides",
    ...overrides,
  };
}

/** The index and coverage load on mount; the proposal only after the button is pressed. */
function stub(response: unknown, status = 200) {
  return vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/contracts/crosswalk")) {
      return Promise.resolve(Response.json(COVERAGE));
    }
    if (url.includes("/api/contracts/map")) {
      return Promise.resolve(Response.json(response, { status }));
    }
    return Promise.resolve(Response.json(INDEX));
  });
}

/** Paste rather than type: `{` is a key descriptor to user-event, and pasting is the real action. */
async function propose(sample = '{"serial_no": "1234ABCD"}') {
  const user = userEvent.setup();
  renderWithProviders(<MappingAssistantView />);
  await user.click(await screen.findByLabelText(/One record from your export/));
  await user.paste(sample);
  await user.click(screen.getByRole("button", { name: /Propose a mapping/ }));
  return user;
}

describe("the adjudication is the answer", () => {
  it("states the schema's verdict, not the model's confidence, as the conclusion", async () => {
    vi.stubGlobal("fetch", stub(proposal()));
    await propose();

    await waitFor(() =>
      expect(screen.getByText(/conformant as a resource record/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/the verdict that counts/)).toBeInTheDocument();
  });

  it("shows a failed verdict even when the model called itself confident", async () => {
    // The case this whole design exists for. A high-confidence invalid proposal must read as a
    // failure, not as a mapping with a footnote.
    vi.stubGlobal(
      "fetch",
      stub(
        proposal({
          model_confidence: "high",
          adjudication: {
            valid: false,
            problem_count: 1,
            problems: [{ pointer: "/identifiers/0/format", message: "'SERIAL_NO' is not one of the allowed formats", rule: "schema" }],
          },
        }),
      ),
    );
    await propose();

    await waitFor(() => expect(screen.getByText(/is NOT conformant/)).toBeInTheDocument());
    expect(screen.getByText(/'SERIAL_NO' is not one of the allowed formats/)).toBeInTheDocument();
    expect(screen.getByText("/identifiers/0/format")).toBeInTheDocument();
    // Confidence is still shown, and still labelled as carrying no weight.
    expect(screen.getByText(/model confidence: high/)).toBeInTheDocument();
  });

  it("calls the proposal a starting point rather than a crosswalk", async () => {
    vi.stubGlobal("fetch", stub(proposal()));
    await propose();

    await waitFor(() =>
      expect(screen.getByText(/A starting point for review, not a crosswalk/)).toBeInTheDocument(),
    );
  });
});

describe("when the model cannot be reached", () => {
  it("offers no fallback mapping, and says why not", async () => {
    // A keyword-matched crosswalk would look exactly like a reasoned one. Refusing is the only
    // answer that leaves the reader able to tell the difference.
    vi.stubGlobal(
      "fetch",
      stub({ ok: false, error: "the endpoint did not answer.", reason: "llm-unavailable" }, 503),
    );
    await propose();

    await waitFor(() =>
      expect(screen.getByText(/reasoning endpoint is unreachable/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/no keyword-matching fallback/)).toBeInTheDocument();
    // And it points at the thing that still works, because the validator never needed a model.
    expect(screen.getByRole("link", { name: "validator" })).toBeInTheDocument();
  });
});

describe("input handling", () => {
  it("rejects a non-JSON sample locally instead of spending a model call", async () => {
    const fetchMock = stub(proposal());
    vi.stubGlobal("fetch", fetchMock);
    await propose("not json at all");

    await waitFor(() => expect(screen.getByText(/must be valid JSON/)).toBeInTheDocument());
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/map"))).toHaveLength(0);
  });

  it("points at the reviewed crosswalk when one already exists for the named system", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", stub(proposal()));
    renderWithProviders(<MappingAssistantView />);

    await user.type(await screen.findByLabelText(/Your tool or system/), "nautobot");

    await waitFor(() =>
      expect(screen.getByText(/already a reviewed crosswalk/)).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: "nautobot" })).toBeInTheDocument();
  });
});
