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
// apiFetch.test.ts — the error contract every service and view depends on.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import { describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, apiJson, onSessionEvent, postJson } from "./apiFetch";

function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

/** Typed like `fetch`, so a test can read back the init that was sent. */
function stub(respond: () => Promise<Response>) {
  const mock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => respond());
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("apiJson", () => {
  it("treats a 200 carrying ok:false as a failure", async () => {
    // The API can answer 200 with `ok: false` -- a validation result, for one. A caller that
    // branched on the status code alone would read that as success.
    stub(() => Promise.resolve(json({ ok: false, error: "nope" })));

    await expect(apiJson("/api/thing")).rejects.toThrow("nope");
  });

  it("carries the stable reason token, not just the message", async () => {
    stub(() =>
      Promise.resolve(
        json({ ok: false, error: "the reasoning endpoint is unreachable", reason: "llm-unavailable" }, 503),
      ),
    );

    // Views branch on `reason`; the message is written for a human and expected to change.
    await expect(apiJson("/api/assessments/")).rejects.toMatchObject({
      reason: "llm-unavailable",
      status: 503,
    });
  });

  it("says something useful when a proxy answers instead of the application", async () => {
    stub(() => Promise.resolve(new Response("<html>502 Bad Gateway</html>", { status: 502 })));

    const error = await apiJson("/api/thing").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).reason).toBe("non-json-response");
    // The point of the special case: not "unexpected token <".
    expect((error as ApiError).message).toContain("between the browser and the application");
  });

  it("keeps the body so a caller can read the extras an endpoint attached", async () => {
    stub(() =>
      Promise.resolve(json({ ok: false, error: "bad", reason: "invalid", problems: [{ pointer: "/a" }] }, 400)),
    );

    const error = (await apiJson("/api/contracts/validate").catch((c: unknown) => c)) as ApiError;
    expect(error.body.problems).toEqual([{ pointer: "/a" }]);
  });
});

describe("session events", () => {
  it("announces an expired session without navigating away", async () => {
    // Redirecting from inside a fetch would discard a half-filled form. The gate decides instead.
    const seen: string[] = [];
    const unsubscribe = onSessionEvent((event) => seen.push(event));
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    stub(() => Promise.resolve(json({ ok: false, error: "no session" }, 401)));

    await apiFetch("/api/repositories/");

    expect(seen).toEqual(["expired"]);
    expect(assign).not.toHaveBeenCalled();
    unsubscribe();
  });

  it("distinguishes a missing session from an insufficient role", async () => {
    // Different remedies: sign in again, versus ask for a group. Conflating them sends the user
    // through a login that will not change the outcome.
    const seen: string[] = [];
    const unsubscribe = onSessionEvent((event) => seen.push(event));
    stub(() => Promise.resolve(json({ ok: false, error: "denied" }, 403)));

    await apiFetch("/api/assessments/");

    expect(seen).toEqual(["forbidden"]);
    unsubscribe();
  });
});

describe("requests", () => {
  it("sends the session cookie and asks for JSON", async () => {
    const fetchMock = stub(() => Promise.resolve(json({ ok: true })));

    await apiJson("/api/health/");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    // Same-origin is the whole reason there is no CORS configuration in this application.
    expect(init.credentials).toBe("same-origin");
    expect((init.headers as Record<string, string>).Accept).toBe("application/json");
  });

  it("only sets a content type when there is a body to describe", async () => {
    const fetchMock = stub(() => Promise.resolve(json({ ok: true })));

    await apiJson("/api/health/");
    expect((fetchMock.mock.calls[0][1] as RequestInit).headers).not.toHaveProperty("Content-Type");

    await postJson("/api/repositories/", { url: "https://example.invalid/x.git" });
    const headers = (fetchMock.mock.calls[1][1] as RequestInit).headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("uses relative URLs, so there is no API base to configure wrong", async () => {
    const fetchMock = stub(() => Promise.resolve(json({ ok: true })));

    await apiJson("/api/contracts/index.json");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/contracts/index.json");
  });
});
