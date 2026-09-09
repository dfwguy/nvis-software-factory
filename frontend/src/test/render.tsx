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
// render.tsx — render a component with the providers it actually needs.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { SessionContext, type SessionValue } from "../context/SessionContext";
import { ThemeProvider } from "../context/ThemeProvider";
import type { Principal } from "../types/api";

export const PRINCIPAL: Principal = {
  subject: "test-subject",
  email: "sa@nvidia.com",
  display_name: "Test SA",
  groups: ["nvis-ova"],
  roles: ["member"],
  effective_roles: ["member", "viewer"],
};

/**
 * Render inside the theme, a router and a session.
 *
 * The session is supplied through the context directly rather than through `SessionProvider`, so
 * a component test does not have to stub `/api/auth/me` to assert on something unrelated to
 * authentication. Tests that are about authentication use the provider.
 */
export function renderWithProviders(
  ui: ReactElement,
  options: { route?: string; session?: Partial<SessionValue> } = {},
) {
  const session: SessionValue = {
    user: PRINCIPAL,
    permissions: new Set(["repository:list", "assessment:create", "contract:read"]),
    loading: false,
    error: null,
    reload: () => {},
    ...options.session,
  };

  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[options.route ?? "/"]}>
        <SessionContext.Provider value={session}>{ui}</SessionContext.Provider>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

/**
 * A fetch stub, typed like `fetch` so a test can read back the init it sent.
 *
 * `routes` is keyed by URL substring; anything unmatched rejects, because a view that quietly
 * fetched something the test did not anticipate is exactly what a test should catch.
 */
export function stubFetch(routes: Record<string, unknown>, status = 200) {
  return vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    const match = Object.keys(routes).find((key) => url.includes(key));
    if (!match) {
      return Promise.reject(new Error(`no stub for ${url}`));
    }
    return Promise.resolve(Response.json(routes[match], { status }));
  });
}

/** The init of the nth request a stub received, for asserting on what was sent. */
export function sentBody(
  stub: ReturnType<typeof stubFetch>,
  index = 0,
): Record<string, unknown> {
  const init = stub.mock.calls[index]?.[1];
  return JSON.parse(String(init?.body)) as Record<string, unknown>;
}
