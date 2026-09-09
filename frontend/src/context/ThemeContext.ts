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
// ThemeContext.ts — the context object and its hook, no components.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// Split from ThemeProvider.tsx deliberately. A module exporting both a component and a hook
// forces React Refresh into a full page reload on every edit; keeping them apart is why editing
// a view refreshes in place.
import { createContext, useContext } from "react";

import type { ThemeMode } from "../theme";

const STORAGE_KEY = "nvsf-theme";

export interface ThemeContextValue {
  mode: ThemeMode;
  toggleTheme: () => void;
}

export const ThemeContext = createContext<ThemeContextValue>({
  mode: "dark",
  toggleTheme: () => {},
});

export const useThemeMode = () => useContext(ThemeContext);

/** Persisted choice, or dark. Read once, when the provider mounts. */
export const getInitialMode = (): ThemeMode => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Private browsing, or storage disabled by policy. Fall through to the default rather than
    // failing to render: a theme preference is not worth a blank page.
  }
  return "dark";
};

export const persistMode = (mode: ThemeMode): void => {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // As above. The toggle still works for this session.
  }
};
