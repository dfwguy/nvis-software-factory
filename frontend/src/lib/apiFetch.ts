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
// apiFetch.ts — the one place the SPA talks to the API.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// Differences from the reference application's version, both because the session model is
// different here:
//
// 1. There is no silent token refresh. Sessions are OIDC and renewing one means a full-page
//    redirect through the identity provider, which cannot happen inside a fetch. So a 401 is
//    reported, not repaired.
// 2. A 401 does NOT redirect on its own. Redirecting from inside a fetch discards whatever the
//    user had typed, and an expired session while filling in a form is exactly when that hurts.
//    Instead the session listener is notified, the gate renders, and the user chooses when to
//    sign in again -- at which point `return_to` brings them back to the same view.

/** Everything a caller needs to explain a failure, in one throwable. */
export class ApiError extends Error {
  readonly status: number;
  /** Stable token from the API (`not-found`, `llm-unavailable`, ...). Branch on this, not on the
   *  message: the message is written for a human and is expected to be improved over time. */
  readonly reason: string | null;
  /** The parsed body, when there was one. Endpoints attach useful extras (`probe`, `problems`). */
  readonly body: Record<string, unknown>;

  constructor(status: number, message: string, reason: string | null, body: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.reason = reason;
    this.body = body;
  }

  get unauthenticated(): boolean {
    return this.status === 401;
  }

  get forbidden(): boolean {
    return this.status === 403;
  }
}

type SessionListener = (event: "expired" | "forbidden") => void;

const listeners = new Set<SessionListener>();

/** Subscribe to authentication outcomes seen by any request. Returns an unsubscribe function. */
export function onSessionEvent(listener: SessionListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function announce(event: "expired" | "forbidden"): void {
  for (const listener of listeners) listener(event);
}

/** Send the browser through the OIDC flow, returning to wherever it is now. */
export function signIn(): void {
  const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  window.location.assign(`/api/auth/login?return_to=${encodeURIComponent(returnTo)}`);
}

export function signOutUrl(): string {
  return "/api/auth/logout";
}

/**
 * A fetch with the session cookie attached and errors normalized.
 *
 * URLs are relative and always will be: the SPA is served by the same Flask app that serves the
 * API, which is what lets a same-origin cookie work with no CORS configuration and no second
 * hostname to keep in sync. There is deliberately no configurable API base URL -- it would only
 * ever be set wrong.
 */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (response.status === 401) announce("expired");
  if (response.status === 403) announce("forbidden");
  return response;
}

/** `apiFetch` plus JSON parsing and the error contract. The form nearly every caller wants. */
export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);

  let body: Record<string, unknown> = {};
  try {
    body = (await response.json()) as Record<string, unknown>;
  } catch {
    // A non-JSON body from an API endpoint means something upstream answered instead of the app
    // -- a proxy error page, or the SPA shell. Say that, rather than "unexpected token <".
    if (!response.ok) {
      throw new ApiError(
        response.status,
        `The server returned ${response.status} with a non-JSON body. Something between the ` +
          `browser and the application answered this request.`,
        "non-json-response",
        {},
      );
    }
  }

  // Every endpoint carries `ok`, so there is one thing to branch on regardless of status code.
  if (!response.ok || body.ok === false) {
    throw new ApiError(
      response.status,
      typeof body.error === "string" ? body.error : `${response.status} ${response.statusText}`,
      typeof body.reason === "string" ? body.reason : null,
      body,
    );
  }

  return body as T;
}

/** The same, for endpoints that answer with text rather than JSON (the agent pack, artifacts). */
export async function apiText(path: string, init?: RequestInit): Promise<string> {
  const response = await apiFetch(path, init);
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`, null, {});
  }
  return response.text();
}

export function postJson<T>(path: string, payload: unknown, init?: RequestInit): Promise<T> {
  return apiJson<T>(path, { ...init, method: "POST", body: JSON.stringify(payload) });
}
