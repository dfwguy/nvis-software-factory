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
// AppLayout.tsx — sidebar, toolbar, scrolling main, footer.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import Box from "@mui/material/Box";
import Divider from "@mui/material/Divider";
import { Text } from "@nvidia/foundations-react-core";
import type { ReactNode } from "react";

interface AppLayoutProps {
  sidebar: ReactNode;
  toolbar: ReactNode;
  children: ReactNode;
  /** The baseline version this deployment judges against. Shown in the footer because every
   *  conclusion in the app is only meaningful next to it. */
  standardsVersion?: string;
  contractVersion?: string;
}

export function AppLayout({
  sidebar,
  toolbar,
  children,
  standardsVersion,
  contractVersion,
}: AppLayoutProps) {
  return (
    <Box sx={{ display: "flex", minHeight: "100vh", overflow: "hidden" }}>
      {sidebar}
      <Box sx={{ flexGrow: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {toolbar}
        {/* `overflow: auto` here rather than on the page means the toolbar stays put while a long
            report scrolls, which is what makes the run's status readable at any scroll depth. */}
        <Box component="main" sx={{ flexGrow: 1, bgcolor: "background.default", overflow: "auto" }}>
          {children}
        </Box>
        <Divider />
        <Box
          component="footer"
          sx={{
            py: 1.5,
            px: 3,
            display: "flex",
            justifyContent: "space-between",
            gap: 2,
            flexWrap: "wrap",
          }}
        >
          <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
            NVIS Software Factory
          </Text>
          <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
            {[
              standardsVersion ? `standards ${standardsVersion}` : null,
              contractVersion ? `NRM ${contractVersion}` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </Text>
        </Box>
      </Box>
    </Box>
  );
}
