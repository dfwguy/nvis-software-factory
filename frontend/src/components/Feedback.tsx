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
// Feedback.tsx — page header, loading, error and empty states.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// One file rather than five, because these are always used together and none is more than a few
// lines. Splitting them would mean five imports at the top of every view to no benefit.
import Box from "@mui/material/Box";
import Skeleton from "@mui/material/Skeleton";
import { Banner, Text } from "@nvidia/foundations-react-core";
import type { ReactNode } from "react";

/** Table-heavy views get the wide bound; prose and forms get the readable one. */
const CONTENT_MAX_WIDTH = { wide: 1600, comfortable: 1100 } as const;

export function Page({
  children,
  width = "wide",
}: {
  children: ReactNode;
  width?: keyof typeof CONTENT_MAX_WIDTH;
}) {
  return (
    <Box sx={{ maxWidth: CONTENT_MAX_WIDTH[width], mx: "auto", p: { xs: 2, md: 4 } }}>
      {children}
    </Box>
  );
}

export function SectionHeading({
  title,
  detail,
  action,
}: {
  title: ReactNode;
  detail?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 2,
        mb: 2,
        flexWrap: "wrap",
      }}
    >
      {/* 24 over 18, which is the pairing Kaizen's own site uses for a section heading and the
          paragraph introducing it. The heading has to move with the detail: an 18px lede under an
          18px heading is the same size twice and reads as one undifferentiated block, which is
          how this app looked when every section was 18 over 14. */}
      <Box sx={{ minWidth: 0 }}>
        <Text kind="body/bold/2xl">{title}</Text>
        {detail && (
          <Text
            kind="body/regular/xl"
            style={{ color: "var(--text-color-secondary)", display: "block", marginTop: 4 }}
          >
            {detail}
          </Text>
        )}
      </Box>
      {action}
    </Box>
  );
}

export function Loading({ rows = 4, label }: { rows?: number; label?: string }) {
  return (
    <Box aria-busy="true" aria-label={label ?? "Loading"}>
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} height={38} sx={{ mb: 1 }} />
      ))}
    </Box>
  );
}

/**
 * An error the user can act on.
 *
 * The API's message is shown verbatim. It is written for a human and names the field or the
 * dependency at fault, and replacing it with "An error occurred" is how a fixable configuration
 * problem becomes a support ticket.
 */
export function ErrorBanner({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Banner status="error" kind="inline">
        {message}
        {action}
      </Banner>
    </Box>
  );
}

export function InfoBanner({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Banner status="info" kind="inline">
        {children}
      </Banner>
    </Box>
  );
}

export function WarningBanner({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Banner status="warning" kind="inline">
        {children}
      </Banner>
    </Box>
  );
}

/**
 * Nothing here yet, and what to do about it.
 *
 * `hint` is not optional by accident. An empty state that says only "No repositories" leaves a
 * first-time user with no next step, and this application's whole purpose is to be the next step.
 */
export function EmptyState({ message, hint }: { message: string; hint: ReactNode }) {
  return (
    <Box sx={{ textAlign: "center", py: 6, px: 2 }}>
      <Text kind="body/bold/lg" style={{ display: "block" }}>
        {message}
      </Text>
      <Text
        kind="body/regular/md"
        style={{ color: "var(--text-color-secondary)", display: "block", marginTop: 8 }}
      >
        {hint}
      </Text>
    </Box>
  );
}
