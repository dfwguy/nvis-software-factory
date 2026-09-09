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
// useApi.ts — the two data-loading shapes this app needs: load-once, and poll-while-live.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// No react-query, no SWR. Two hooks cover every view here, and a caching layer whose
// invalidation rules nobody remembers is a worse outcome than an explicit refresh call.
//
// Both hooks share three properties that are the reason they exist rather than being written per
// view:
//
//   1. State is only touched after an `await`, so nothing sets state synchronously from an
//      effect. That is what lets react-hooks/set-state-in-effect stay an error in this repo.
//   2. Every request is abort-guarded, and a response that arrives after unmount or after a newer
//      request is discarded. Navigating away mid-load is normal, not exceptional.
//   3. On failure, previously loaded data is KEPT and the error is reported alongside it. A poll
//      that fails once should not blank a page the user is reading.
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../lib/apiFetch";

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  /** Present when the failure came from the API, for callers that branch on `reason`. */
  apiError: ApiError | null;
  refresh: () => void;
}

function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong";
}

/**
 * Load once, and again whenever `deps` change or `refresh` is called.
 *
 * `loader` is expected to be a stable reference (a module-level service function, or wrapped in
 * useCallback). It receives an AbortSignal and must pass it through.
 */
export function useApi<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[] = [],
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<ApiError | null>(null);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let live = true;

    (async () => {
      try {
        const result = await loader(controller.signal);
        if (!live) return;
        setData(result);
        setError(null);
        setApiError(null);
      } catch (caught) {
        if (!live || controller.signal.aborted) return;
        setError(messageOf(caught));
        setApiError(caught instanceof ApiError ? caught : null);
      } finally {
        if (live) setLoading(false);
      }
    })();

    return () => {
      live = false;
      controller.abort();
    };
    // `deps` is the caller's declared dependency list and spreading it is the point; `loader` is
    // required to be stable, which the rule cannot see from here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  return { data, loading, error, apiError, refresh };
}

export interface PollingState<T> extends AsyncState<T> {
  /** Whether the hook is currently polling. False once `shouldPoll` returns false. */
  polling: boolean;
}

/**
 * Load, then keep loading on an interval for as long as the data says it is still changing.
 *
 * `shouldPoll` is what stops it: an assessment that has finished is not going to change, and a
 * page left open on a completed run should not keep asking. Polling rather than a websocket or
 * SSE is deliberate -- a run produces a handful of state transitions over minutes, and a poll is
 * something an SSH tunnel and a restarting container both survive without reconnect logic.
 */
export function usePolling<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  shouldPoll: (data: T | null) => boolean,
  intervalMs = 3000,
  deps: readonly unknown[] = [],
): PollingState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<ApiError | null>(null);
  const [polling, setPolling] = useState(true);
  const [tick, setTick] = useState(0);

  // Held in a ref so changing the predicate does not restart the timer, and so the running loop
  // always sees the current one. Synchronised in an effect rather than during render: the loop
  // only ever reads it after an await, so a commit-time assignment is soon enough, and writing a
  // ref during render is the pattern that breaks under concurrent rendering.
  const predicate = useRef(shouldPoll);
  useEffect(() => {
    predicate.current = shouldPoll;
  }, [shouldPoll]);

  const refresh = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const run = async () => {
      try {
        const result = await loader(controller.signal);
        if (!live) return;
        setData(result);
        setError(null);
        setApiError(null);

        if (predicate.current(result)) {
          timer = setTimeout(() => void run(), intervalMs);
        } else {
          setPolling(false);
        }
      } catch (caught) {
        if (!live || controller.signal.aborted) return;
        setError(messageOf(caught));
        setApiError(caught instanceof ApiError ? caught : null);

        // A 404 or a 403 will not fix itself, so stop. Anything else might be a restart or a
        // brief network fault, and continuing to poll is how the page recovers on its own.
        const terminal = caught instanceof ApiError && [401, 403, 404].includes(caught.status);
        if (terminal) {
          setPolling(false);
        } else {
          timer = setTimeout(() => void run(), intervalMs * 2);
        }
      } finally {
        if (live) setLoading(false);
      }
    };

    void run();

    return () => {
      live = false;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
    // As above: the caller's dependency list, spread deliberately.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, intervalMs, ...deps]);

  return { data, loading, error, apiError, refresh, polling };
}
