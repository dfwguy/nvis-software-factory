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
// format.ts — display helpers.
// Author: Rafael M. Koike & Cursor Agent ("Ada")

/**
 * A timestamp as both relative and absolute.
 *
 * Relative for reading ("4 minutes ago"), absolute in the tooltip for correlating with a log.
 * Relative alone is useless when someone asks what happened at 14:07.
 */
export function when(iso: string | null | undefined): { relative: string; absolute: string } {
  if (!iso) return { relative: "—", absolute: "" };

  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return { relative: iso, absolute: iso };

  const seconds = Math.round((Date.now() - then.getTime()) / 1000);
  const absolute = then.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });

  const relative =
    seconds < 5
      ? "just now"
      : seconds < 60
        ? `${seconds}s ago`
        : seconds < 3600
          ? `${Math.round(seconds / 60)}m ago`
          : seconds < 86400
            ? `${Math.round(seconds / 3600)}h ago`
            : `${Math.round(seconds / 86400)}d ago`;

  return { relative, absolute };
}

/** How long a run took, from its own timestamps. */
export function duration(startedAt: string | null, finishedAt: string | null): string {
  if (!startedAt) return "—";
  const start = new Date(startedAt).getTime();
  const end = finishedAt ? new Date(finishedAt).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) return "—";

  const seconds = Math.max(0, Math.round((end - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

/** A measured latency. Sub-second stays in milliseconds, because that is how it is compared. */
export function millis(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`;
}

export function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

/** Thousands separators. Token counts get large enough that 184320 is hard to read. */
export function count(value: number | null | undefined): string {
  return typeof value === "number" ? value.toLocaleString() : "—";
}

/**
 * A repository URL as `namespace/name`, falling back to the URL.
 *
 * The full URL is 60 characters of which 40 are the same on every row, and a table where every
 * row starts with the same 40 characters is a table you cannot scan.
 */
export function repoLabel(repo: { namespace: string | null; name: string | null; url: string }): string {
  if (repo.namespace && repo.name) return `${repo.namespace}/${repo.name}`;
  return repo.name ?? repo.url;
}

/** A short commit sha, or an em dash. */
export function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 8) : "—";
}

/**
 * A pillar id as a title, for the cases where only the id is at hand.
 *
 * The real titles come from /api/standards and are preferred wherever they are available; this is
 * for findings, which carry only `pillar_id`.
 */
export function pillarLabel(id: string): string {
  return id.replace(/-/g, " ").replace(/^./, (c) => c.toUpperCase());
}
