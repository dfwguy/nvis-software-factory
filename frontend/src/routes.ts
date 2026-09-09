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
// routes.ts — every path in the app, in one place.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// One table, read by the router, the sidebar and the breadcrumb. A path written as a string
// literal in a component is a path that survives a rename in one place and not the other.
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BookOpen,
  Boxes,
  CheckCircle2,
  FileJson,
  GitBranch,
  HeartPulse,
  Wand2,
} from "lucide-react";

export type ViewId =
  | "repositories"
  | "repository-detail"
  | "assessments"
  | "assessment-detail"
  | "golden-path"
  | "pillar-detail"
  | "contract-explorer"
  | "entity-detail"
  | "crosswalks"
  | "crosswalk-detail"
  | "validate"
  | "mapping-assistant"
  | "platform";

export interface RouteDef {
  viewId: ViewId;
  path: string;
  label: string;
  /** Sidebar group. Null keeps the route out of the nav -- detail views are reached from a list. */
  group: string | null;
  icon?: LucideIcon;
  /** Shown in the toolbar under the title. One line, what the view is for. */
  blurb?: string;
}

export const REPOSITORIES_PATH = "/repositories";
export const ASSESSMENTS_PATH = "/assessments";
export const CONTRACT_PATH = "/contract";
export const GOLDEN_PATH = "/golden-path";
export const DEFAULT_PATH = REPOSITORIES_PATH;

export const repositoryPath = (id: string) => `${REPOSITORIES_PATH}/${encodeURIComponent(id)}`;
export const assessmentPath = (id: string) => `${ASSESSMENTS_PATH}/${encodeURIComponent(id)}`;
export const entityPath = (name: string) => `${CONTRACT_PATH}/entity/${encodeURIComponent(name)}`;
export const crosswalkPath = (system: string) =>
  `${CONTRACT_PATH}/crosswalk/${encodeURIComponent(system)}`;
export const pillarPath = (id: string) => `${GOLDEN_PATH}/${encodeURIComponent(id)}`;

/**
 * Resolve a link written inside a `standards/` Markdown file to a route in this application.
 *
 * Those files cross-reference each other by repository path, because on disk that is what they
 * are: `standards/README.md` links to `pillars/durability.md`. The same pillar is served here at
 * `/golden-path/durability`, so the two are one thing addressed two ways, and this is the only
 * place that needs to know it. Without this the reader sees literal `[label](pillars/x.md)`.
 *
 * Deliberately narrow: it matches the `pillars/` prefix and nothing else, so a future link to
 * some other document is left as text rather than silently pointed at a route that does not
 * exist. Returns null when it does not recognise the target.
 */
export function resolveStandardsLink(href: string): string | null {
  const match = /^(?:\.{1,2}\/)*pillars\/([A-Za-z0-9._-]+)\.md$/.exec(href);
  return match ? `#${pillarPath(match[1])}` : null;
}

export const ROUTES: RouteDef[] = [
  {
    viewId: "repositories",
    path: REPOSITORIES_PATH,
    label: "Repositories",
    group: "Software factory",
    icon: GitBranch,
    blurb: "Register a repository and assess it against the baseline.",
  },
  {
    viewId: "repository-detail",
    path: `${REPOSITORIES_PATH}/:repositoryId`,
    label: "Repository",
    group: null,
  },
  {
    viewId: "assessments",
    path: ASSESSMENTS_PATH,
    label: "Assessments",
    group: "Software factory",
    icon: Activity,
    blurb: "Every run, with what it concluded and what it cost.",
  },
  {
    viewId: "assessment-detail",
    path: `${ASSESSMENTS_PATH}/:assessmentId`,
    label: "Assessment",
    group: null,
  },
  {
    viewId: "golden-path",
    path: GOLDEN_PATH,
    label: "Golden path",
    group: "Standards",
    icon: CheckCircle2,
    blurb: "What good looks like: the eight pillars every assessment judges against.",
  },
  {
    viewId: "pillar-detail",
    path: `${GOLDEN_PATH}/:pillarId`,
    label: "Pillar",
    group: null,
  },
  {
    viewId: "contract-explorer",
    path: CONTRACT_PATH,
    label: "Contract explorer",
    group: "NVIS Resource Model",
    icon: Boxes,
    blurb: "The entities, their fields, and the reasoning behind each one.",
  },
  {
    viewId: "entity-detail",
    path: `${CONTRACT_PATH}/entity/:entity`,
    label: "Entity",
    group: null,
  },
  {
    viewId: "crosswalks",
    path: `${CONTRACT_PATH}/crosswalk`,
    label: "Crosswalks",
    group: "NVIS Resource Model",
    icon: FileJson,
    blurb: "How Nautobot, Redfish, UFM, BCM and DCGM map onto the contract.",
  },
  {
    viewId: "crosswalk-detail",
    path: `${CONTRACT_PATH}/crosswalk/:system`,
    label: "Crosswalk",
    group: null,
  },
  {
    viewId: "validate",
    path: `${CONTRACT_PATH}/validate`,
    label: "Validate",
    group: "NVIS Resource Model",
    icon: CheckCircle2,
    blurb: "Paste an export. The schema decides, not a model.",
  },
  {
    viewId: "mapping-assistant",
    path: `${CONTRACT_PATH}/map`,
    label: "Mapping assistant",
    group: "NVIS Resource Model",
    icon: Wand2,
    blurb: "The model proposes a crosswalk; the schema adjudicates it.",
  },
  {
    viewId: "platform",
    path: "/platform",
    label: "Platform health",
    group: "Platform",
    icon: HeartPulse,
    blurb: "Store, migrations, backups, reasoning endpoint, identity.",
  },
];

/** Nav groups in the order they are meant to be read. */
export const NAV_GROUPS = ["Software factory", "Standards", "NVIS Resource Model", "Platform"];

/** Links out of the SPA. Served by Flask, not the router, so they are plain anchors. */
export const EXTERNAL_LINKS = [
  { label: "Documentation", href: "/docs/", icon: BookOpen },
  { label: "OpenAPI", href: "/api/openapi.json", icon: FileJson },
];

function segments(path: string): string[] {
  return path.split("/").filter(Boolean);
}

/**
 * The route a path belongs to, matched segment by segment.
 *
 * Segment matching rather than prefix matching, because `/contract/crosswalk` is both the
 * crosswalk list and the prefix of `/contract/crosswalk/:system`. A prefix match resolves the
 * list page to the detail route and titles it "Crosswalk", singular, with no crosswalk on it.
 *
 * Where a static segment and a parameter both fit, the static one wins -- the same specificity
 * rule the router applies, so this function and the rendered view never disagree.
 */
export function routeFor(pathname: string): RouteDef | undefined {
  const parts = segments(pathname);

  const matches = ROUTES.filter((route) => {
    const pattern = segments(route.path);
    if (pattern.length !== parts.length) return false;
    return pattern.every((segment, i) => segment.startsWith(":") || segment === parts[i]);
  });

  // Fewest parameters first: the most specific match.
  return matches.sort(
    (a, b) =>
      segments(a.path).filter((s) => s.startsWith(":")).length -
      segments(b.path).filter((s) => s.startsWith(":")).length,
  )[0];
}

/** The nav entry to highlight for a path: the detail view's parent, or the route itself. */
export function activeViewFor(pathname: string): ViewId | undefined {
  const route = routeFor(pathname);
  if (!route) return undefined;
  const parents: Partial<Record<ViewId, ViewId>> = {
    "repository-detail": "repositories",
    "assessment-detail": "assessments",
    "pillar-detail": "golden-path",
    "entity-detail": "contract-explorer",
    "crosswalk-detail": "crosswalks",
  };
  return parents[route.viewId] ?? route.viewId;
}
