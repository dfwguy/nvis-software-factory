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
// SessionContext.ts — the session context and its hooks, no components.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import { createContext, useContext } from "react";

import type { Principal } from "../types/api";

export interface SessionValue {
  user: Principal | null;
  /** Actions this principal may perform, from the server. */
  permissions: Set<string>;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export const SessionContext = createContext<SessionValue>({
  user: null,
  permissions: new Set(),
  loading: true,
  error: null,
  reload: () => {},
});

export const useSession = () => useContext(SessionContext);

/**
 * Whether the UI should offer a control.
 *
 * A usability measure and nothing more. The server checks every request in the audit hook, so
 * hiding a button is about not offering an action that will fail -- it is not the control. Any
 * reasoning here that treats it as security is wrong.
 */
export function useCan(action: string): boolean {
  const { permissions } = useSession();
  return permissions.has(action);
}
