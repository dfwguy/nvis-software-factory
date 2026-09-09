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
// SignInGate.tsx — what an unauthenticated visitor sees.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import { Button, Text } from "@nvidia/foundations-react-core";
import { Factory } from "lucide-react";
import type { ReactNode } from "react";

import { useSession } from "../context/SessionContext";
import { signIn } from "../lib/apiFetch";
import { ErrorBanner } from "./Feedback";

/**
 * Renders children only once there is a session.
 *
 * A full-page gate rather than a per-view redirect. Authentication is OIDC-only and there is no
 * anonymous mode, so a partially-rendered shell around a sign-in prompt would be showing chrome
 * for data the visitor cannot see.
 */
export function SignInGate({ children }: { children: ReactNode }) {
  const { user, loading, error, reload } = useSession();

  if (loading) {
    return (
      <Box
        sx={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <CircularProgress size={28} />
      </Box>
    );
  }

  if (user) return <>{children}</>;

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 2,
        px: 3,
        textAlign: "center",
      }}
    >
      <Factory size={40} color="var(--text-color-brand, #76b900)" />
      <Text kind="display/sm">NVIS Software Factory</Text>
      <Text
        kind="body/regular/md"
        style={{ color: "var(--text-color-secondary)", maxWidth: 520 }}
      >
        Assess a repository against the NVIS quality baseline, and read the NVIS Resource Model
        contract your tools exchange data through.
      </Text>

      {/* An error here is a real configuration failure -- an unregistered OIDC client, a missing
          issuer -- and its message names which. Showing it beats "sign-in failed", which sends
          the reader to a support channel to be told the same thing. */}
      {error && (
        <Box sx={{ maxWidth: 560, width: "100%", textAlign: "left" }}>
          <ErrorBanner
            message={error}
            action={
              <Box sx={{ mt: 1 }}>
                <Button kind="secondary" size="small" onClick={reload}>
                  Try again
                </Button>
              </Box>
            }
          />
        </Box>
      )}

      <Button kind="primary" color="brand" onClick={signIn}>
        Sign in
      </Button>
    </Box>
  );
}
