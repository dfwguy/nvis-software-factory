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
// Sidebar.tsx — primary navigation. Kaizen VerticalNav when open, MUI icon rail when collapsed.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// The one structural difference from the reference application: destinations are real router
// links, not `onNavigate(viewId)` callbacks. The reference derives its active view from the URL
// but navigates through state, which means the nav and the router each hold half the answer.
// Here the URL is the only source, so a middle-click opens a new tab and a deep link works.
import Box from "@mui/material/Box";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import Tooltip from "@mui/material/Tooltip";
import { Text, VerticalNav, type VerticalNavBaseItem } from "@nvidia/foundations-react-core";
import { ChevronLeft, Factory } from "lucide-react";
import { Link } from "react-router-dom";

import { EXTERNAL_LINKS, NAV_GROUPS, ROUTES, type RouteDef, type ViewId } from "../routes";

// rem, not px, because the drawer's job is to hold text. A bare number here becomes a pixel
// value that stays put while the labels inside it grow with the root font size, so the longest
// item -- "Mapping assistant" -- starts truncating and the product name wraps. That is not
// hypothetical: it is what this sidebar does at a 125% root, and a reader who has raised their
// browser's default font size for legibility gets it without touching anything.
//
// 15.5rem and 4rem are the previous 248px and 64px at a 16px root, so the default rendering is
// unchanged and the width now tracks the text.
export const DRAWER_WIDTH_OPEN = "15.5rem";
export const DRAWER_WIDTH_CLOSED = "4rem";

const ICON_SIZE = 20;

interface SidebarProps {
  open: boolean;
  onToggle: () => void;
  activeView: ViewId | undefined;
}

/** Only routes that belong in the nav; detail views are reached from their list. */
const navigable = ROUTES.filter((route) => route.group !== null);

function iconFor(route: RouteDef) {
  const Icon = route.icon;
  return Icon ? <Icon size={ICON_SIZE} /> : null;
}

function ExpandedNav({ activeView }: { activeView: ViewId | undefined }) {
  const items: VerticalNavBaseItem[] = NAV_GROUPS.map((group) => {
    const leaves = navigable.filter((route) => route.group === group);
    return {
      id: `grp-${group}`,
      children: group,
      // Open by default. There are four groups holding eight destinations between them, so
      // everything fits without scrolling -- collapsing them would hide the app's shape to save
      // space there is no shortage of.
      defaultOpen: true,
      subItems: leaves.map((route) => ({
        id: route.viewId,
        active: activeView === route.viewId,
        slotIcon: iconFor(route),
        asChild: true,
        children: <Link to={route.path}>{route.label}</Link>,
      })),
    };
  });

  const bottom: VerticalNavBaseItem[] = EXTERNAL_LINKS.map(({ label, href, icon: Icon }) => ({
    id: `ext-${label}`,
    slotIcon: <Icon size={ICON_SIZE} />,
    asChild: true,
    // A real anchor, not a router link: these are served by Flask, and routing them through the
    // SPA would resolve them to the shell.
    children: <a href={href}>{label}</a>,
  }));

  return (
    <>
      <Box
        component="nav"
        aria-label="Primary navigation"
        sx={{ flexGrow: 1, overflowY: "auto", pt: 1 }}
      >
        <VerticalNav items={items} />
      </Box>
      <Divider />
      <Box component="nav" aria-label="Documentation" sx={{ py: 1 }}>
        <VerticalNav items={bottom} />
      </Box>
    </>
  );
}

/**
 * Collapsed rail: icons only, with tooltips.
 *
 * Kaizen's grouped VerticalNav does not render as a 64px icon rail, so this is a flat MUI list.
 * The Drawer shell is MUI too, so the two agree visually.
 */
function CollapsedRail({ activeView }: { activeView: ViewId | undefined }) {
  return (
    <Box sx={{ flexGrow: 1, pt: 1 }}>
      <List disablePadding>
        {navigable.map((route) => {
          const active = activeView === route.viewId;
          return (
            <ListItem key={route.viewId} disablePadding sx={{ display: "block" }}>
              <Tooltip title={route.label} placement="right" arrow>
                <ListItemButton
                  component={Link}
                  to={route.path}
                  sx={{
                    minHeight: 44,
                    px: 0,
                    justifyContent: "center",
                    bgcolor: active ? "action.selected" : "transparent",
                    borderRight: active ? 3 : 0,
                    borderColor: "primary.main",
                    "&:hover": { bgcolor: "action.hover" },
                  }}
                >
                  <ListItemIcon
                    sx={{
                      minWidth: 0,
                      justifyContent: "center",
                      color: active ? "primary.main" : "text.secondary",
                    }}
                  >
                    {iconFor(route)}
                  </ListItemIcon>
                </ListItemButton>
              </Tooltip>
            </ListItem>
          );
        })}
      </List>
      <Divider sx={{ my: 1 }} />
      <List disablePadding>
        {EXTERNAL_LINKS.map(({ label, href, icon: Icon }) => (
          <ListItem key={label} disablePadding sx={{ display: "block" }}>
            <Tooltip title={label} placement="right" arrow>
              <ListItemButton
                component="a"
                href={href}
                sx={{ minHeight: 44, px: 0, justifyContent: "center" }}
              >
                <ListItemIcon
                  sx={{ minWidth: 0, justifyContent: "center", color: "text.secondary" }}
                >
                  <Icon size={ICON_SIZE} />
                </ListItemIcon>
              </ListItemButton>
            </Tooltip>
          </ListItem>
        ))}
      </List>
    </Box>
  );
}

export function Sidebar({ open, onToggle, activeView }: SidebarProps) {
  const width = open ? DRAWER_WIDTH_OPEN : DRAWER_WIDTH_CLOSED;

  return (
    <Drawer
      variant="permanent"
      sx={{
        width,
        flexShrink: 0,
        "& .MuiDrawer-paper": {
          width,
          overflowX: "hidden",
          transition: "width 225ms cubic-bezier(0.4, 0, 0.6, 1)",
        },
      }}
    >
      <Box
        sx={(theme) => ({
          display: "flex",
          alignItems: "center",
          gap: 1,
          px: open ? 2 : 0,
          justifyContent: open ? "space-between" : "center",
          ...theme.mixins.toolbar,
        })}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, minWidth: 0 }}>
          <Factory size={26} color="var(--text-color-brand, #76b900)" />
          {open && <Text kind="body/bold/md">Software Factory</Text>}
        </Box>
        {open && (
          <IconButton
            size="small"
            onClick={onToggle}
            aria-label="Collapse navigation"
            sx={{ color: "text.secondary" }}
          >
            <ChevronLeft size={22} />
          </IconButton>
        )}
      </Box>

      <Divider />

      {open ? <ExpandedNav activeView={activeView} /> : <CollapsedRail activeView={activeView} />}
    </Drawer>
  );
}
