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
// setup.ts — jsdom shims and the fetch guard.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// jsdom implements neither of these, and MUI's responsive `sx` breakpoints call matchMedia on
// first render, so without this every component test fails before reaching its assertion.
beforeEach(() => {
  if (!window.matchMedia) {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })) as unknown as typeof window.matchMedia;
  }

  // Any test that renders a data-loading view must state what the API returns. Left unstubbed, a
  // real fetch to a relative URL in jsdom produces an unhandled rejection that surfaces as a
  // confusing failure in an unrelated test, so failing loudly here is the kinder outcome.
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(new Error("unstubbed fetch: stub it in the test that needs it"))),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
