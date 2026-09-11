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
// Toolbar.tsx — page title, deployment warnings, theme toggle, session.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import MuiToolbar from "@mui/material/Toolbar";
import Tooltip from "@mui/material/Tooltip";
import { Tag, Text } from "@nvidia/foundations-react-core";
import { LogOut, Menu, Moon, Sun } from "lucide-react";

import { useSession } from "../context/SessionContext";
import { useThemeMode } from "../context/ThemeContext";
import { signOutUrl } from "../lib/apiFetch";

import { Breadcrumbs } from "./Breadcrumbs";

interface ToolbarProps {
  title: string;
  blurb?: string;
  sidebarOpen: boolean;
  onOpenSidebar: () => void;
}

export function Toolbar({ title, blurb, sidebarOpen, onOpenSidebar }: ToolbarProps) {
  const { mode, toggleTheme } = useThemeMode();
  const { user } = useSession();

  return (
    <AppBar position="sticky" elevation={0}>
      <MuiToolbar sx={{ gap: 2 }}>
        {!sidebarOpen && (
          <IconButton edge="start" onClick={onOpenSidebar} aria-label="Open navigation">
            <Menu size={20} />
          </IconButton>
        )}

        <Box sx={{ minWidth: 0, flexGrow: 1 }}>
          {/* Above the title, inside the sticky toolbar: the way out of a page stays reachable at
              any scroll depth, and an assessment report is long enough that it matters. Renders
              nothing on a top-level page. */}
          <Breadcrumbs />
          <Text kind="body/bold/lg">{title}</Text>
          {blurb && (
            <Text
              kind="body/regular/md"
              style={{ color: "var(--text-color-secondary)", display: "block" }}
            >
              {blurb}
            </Text>
          )}
        </Box>

        {/* A deployment accidentally running on the loopback mock provider must be impossible to
            miss: every request there is the same fixed development user, so anything the audit
            trail attributes to a person is wrong. */}
        {user?.is_mock && (
          <Tooltip title="Every request is a fixed development user. Not for production.">
            <span>
              <Tag color="yellow" kind="solid" readOnly density="compact">
                mock identity
              </Tag>
            </span>
          </Tooltip>
        )}

        <Tooltip title={mode === "dark" ? "Switch to light theme" : "Switch to dark theme"}>
          <IconButton onClick={toggleTheme} aria-label="Toggle theme">
            {mode === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </IconButton>
        </Tooltip>

        {user && (
          <>
            <Tooltip
              title={`${user.email ?? user.subject} — roles: ${user.effective_roles.join(", ")}`}
            >
              <span>
                <Tag color="gray" kind="solid" readOnly density="compact">
                  {user.display_name ?? user.subject}
                </Tag>
              </span>
            </Tooltip>
            <Tooltip title="Sign out">
              {/* A plain anchor: signing out is a full-page navigation that ends at the identity
                  provider, which a fetch cannot do. */}
              <IconButton component="a" href={signOutUrl()} aria-label="Sign out">
                <LogOut size={18} />
              </IconButton>
            </Tooltip>
          </>
        )}
      </MuiToolbar>
    </AppBar>
  );
}
