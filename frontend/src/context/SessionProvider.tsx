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
// SessionProvider.tsx — discovers the session once, and notices when it expires.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import { useEffect, useMemo, type ReactNode } from "react";

import { useApi } from "../hooks/useApi";
import { onSessionEvent } from "../lib/apiFetch";
import { getSession } from "../services/platform";
import { SessionContext } from "./SessionContext";

export const SessionProvider = ({ children }: { children: ReactNode }) => {
  const { data, loading, error, apiError, refresh } = useApi(getSession);

  // Any request anywhere in the app that sees a 401 re-checks the session, which flips this
  // provider to unauthenticated and renders the gate. The alternative -- each view handling its
  // own 401 -- means the first view to notice wins and the rest keep showing stale data.
  useEffect(() => onSessionEvent((event) => {
    if (event === "expired") refresh();
  }), [refresh]);

  const value = useMemo(() => ({
    user: data?.user ?? null,
    permissions: new Set(data?.permissions ?? []),
    loading,
    // A 401 is not an error here: it is the answer, and the answer is "sign in". Reporting it as
    // a failure would show a red banner to every first-time visitor.
    error: apiError?.unauthenticated ? null : error,
    reload: refresh,
  }), [data, loading, error, apiError, refresh]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
};
