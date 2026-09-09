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
// ThemeProvider.tsx — Kaizen owns the theme, MUI is bridged to follow it.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import CssBaseline from "@mui/material/CssBaseline";
import { ThemeProvider as MuiThemeProvider } from "@mui/material/styles";
import {
  ThemeProvider as KuiThemeProvider,
  useTheme as useKuiTheme,
} from "@nvidia/foundations-react-core";
import { useCallback, useMemo, type ReactNode } from "react";

import { getTheme, type ThemeMode } from "../theme";
import { getInitialMode, persistMode, ThemeContext } from "./ThemeContext";

/** Mirrors the Kaizen theme into MUI and into our context, so one toggle drives all three. */
const ThemeBridge = ({ children }: { children: ReactNode }) => {
  const { theme, setTheme } = useKuiTheme();

  const mode: ThemeMode = theme === "light" ? "light" : "dark";

  const toggleTheme = useCallback(() => {
    const next: ThemeMode = mode === "dark" ? "light" : "dark";
    setTheme(next);
    persistMode(next);
  }, [mode, setTheme]);

  const muiTheme = useMemo(() => getTheme(mode), [mode]);
  const value = useMemo(() => ({ mode, toggleTheme }), [mode, toggleTheme]);

  return (
    <ThemeContext.Provider value={value}>
      <MuiThemeProvider theme={muiTheme}>
        <CssBaseline />
        {children}
      </MuiThemeProvider>
    </ThemeContext.Provider>
  );
};

export const ThemeProvider = ({ children }: { children: ReactNode }) => (
  <KuiThemeProvider theme={getInitialMode()} global>
    <ThemeBridge>{children}</ThemeBridge>
  </KuiThemeProvider>
);
