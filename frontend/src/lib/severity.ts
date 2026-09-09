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
// severity.ts — the severity scale as a CSS value.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// Not in labels.tsx with the badges, even though that is where it belongs conceptually: a file
// that exports both components and plain functions breaks Fast Refresh, and this is the function
// side of that pair.
import type { Severity } from "../types/api";

/** The token for a severity, for borders and accents that are not badges. */
export function severityColor(severity: Severity): string {
  return `var(--sev-${severity})`;
}

/** Worst first. The order every list of findings in this application is sorted by. */
export const SEVERITY_ORDER: readonly Severity[] = ["blocker", "major", "minor", "info"];

/** Sort comparator over anything carrying a severity, worst first. */
export function bySeverity(a: { severity: Severity }, b: { severity: Severity }): number {
  return SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity);
}
