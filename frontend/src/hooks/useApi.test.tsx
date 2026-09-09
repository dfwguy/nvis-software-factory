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
// useApi.test.tsx — the three properties both hooks are supposed to guarantee.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../lib/apiFetch";
import { useApi, usePolling } from "./useApi";

describe("useApi", () => {
  it("loads once and reports the data", async () => {
    const loader = vi.fn(() => Promise.resolve({ value: 1 }));
    const { result } = renderHook(() => useApi(loader));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual({ value: 1 });
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("keeps the data it already had when a later load fails", async () => {
    // A page the user is reading must not be blanked by one failed request. The error is
    // reported next to the stale data instead, which is the honest state.
    let attempt = 0;
    const loader = vi.fn(() => {
      attempt += 1;
      return attempt === 1
        ? Promise.resolve({ value: "first" })
        : Promise.reject(new Error("upstream went away"));
    });

    const { result } = renderHook(() => useApi(loader));
    await waitFor(() => expect(result.current.data).toEqual({ value: "first" }));

    act(() => result.current.refresh());

    await waitFor(() => expect(result.current.error).toBe("upstream went away"));
    expect(result.current.data).toEqual({ value: "first" });
  });

  it("hands an ApiError through so a view can branch on its reason", async () => {
    const loader = vi.fn(() =>
      Promise.reject(new ApiError(503, "unreachable", "llm-unavailable", {})),
    );
    const { result } = renderHook(() => useApi(loader));

    await waitFor(() => expect(result.current.apiError?.reason).toBe("llm-unavailable"));
  });

  it("reloads when refresh is called", async () => {
    const loader = vi.fn(() => Promise.resolve(1));
    const { result } = renderHook(() => useApi(loader));

    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.refresh());

    await waitFor(() => expect(loader).toHaveBeenCalledTimes(2));
  });

  it("aborts the request when the component unmounts", async () => {
    // Navigating away mid-load is normal. An un-aborted request lands on an unmounted component
    // and, worse, keeps a stale response racing against the new view's.
    let signal: AbortSignal | undefined;
    const loader = vi.fn((s: AbortSignal) => {
      signal = s;
      return new Promise<number>(() => {});
    });

    const { unmount } = renderHook(() => useApi(loader));
    await waitFor(() => expect(signal).toBeDefined());
    unmount();

    expect(signal?.aborted).toBe(true);
  });

  it("discards a response that arrives after unmount", async () => {
    let resolve: ((value: number) => void) | undefined;
    const loader = vi.fn(
      () =>
        new Promise<number>((r) => {
          resolve = r;
        }),
    );

    const { unmount } = renderHook(() => useApi(loader));
    unmount();
    // No "state update on an unmounted component" warning, and no throw.
    resolve?.(7);
    await Promise.resolve();
  });
});

describe("usePolling", () => {
  it("keeps polling while the data says the run is still moving", async () => {
    const loader = vi.fn(() => Promise.resolve({ status: "reasoning" }));
    const { result } = renderHook(() =>
      usePolling(loader, (data) => data?.status !== "complete", 10),
    );

    await waitFor(() => expect(loader.mock.calls.length).toBeGreaterThan(2));
    expect(result.current.polling).toBe(true);
  });

  it("stops once the run reaches a terminal state", async () => {
    // A finished assessment cannot change. A page left open on one must stop asking.
    const loader = vi.fn(() => Promise.resolve({ status: "complete" }));
    const { result } = renderHook(() =>
      usePolling(loader, (data) => data?.status !== "complete", 10),
    );

    await waitFor(() => expect(result.current.polling).toBe(false));
    const calls = loader.mock.calls.length;
    await new Promise((r) => setTimeout(r, 50));
    expect(loader.mock.calls.length).toBe(calls);
  });

  it("stops on a 404, which will not fix itself", async () => {
    const loader = vi.fn(() => Promise.reject(new ApiError(404, "no such run", "not-found", {})));
    const { result } = renderHook(() => usePolling(loader, () => true, 10));

    await waitFor(() => expect(result.current.polling).toBe(false));
    expect(result.current.error).toBe("no such run");
  });

  it("keeps trying after a transient failure, so the page recovers on its own", async () => {
    // A container restart or a brief network fault is the common case, and the alternative is a
    // page that stays stuck until the user reloads it.
    let attempt = 0;
    const loader = vi.fn(() => {
      attempt += 1;
      return attempt === 1
        ? Promise.reject(new Error("connection reset"))
        : Promise.resolve({ status: "reasoning" });
    });

    const { result } = renderHook(() =>
      usePolling(loader, (data) => data?.status !== "complete", 10),
    );

    await waitFor(() => expect(result.current.data).toEqual({ status: "reasoning" }));
    expect(result.current.polling).toBe(true);
  });

  it("stops the timer on unmount", async () => {
    const loader = vi.fn(() => Promise.resolve({ status: "reasoning" }));
    const { unmount } = renderHook(() =>
      usePolling(loader, (data) => data?.status !== "complete", 10),
    );

    await waitFor(() => expect(loader).toHaveBeenCalled());
    unmount();
    const calls = loader.mock.calls.length;

    await new Promise((r) => setTimeout(r, 60));
    expect(loader.mock.calls.length).toBe(calls);
  });
});
