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
// Breadcrumbs.tsx — where you are, and one click back out of it.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// The assessment detail view is three clicks deep -- repositories, a repository, one of its runs
// -- and had no way back up. Every escape route was the sidebar, which jumps to a list rather than
// returning to the one you were reading, so comparing two runs of the same repository meant
// starting the descent again.
//
// The back button and the trail are deliberately both here. The trail answers "where am I", and
// on a wide toolbar it is also the fastest way to any ancestor. The button answers "get me out of
// here" without asking the reader to aim at a short piece of text.
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import { ArrowLeft, ChevronRight } from "lucide-react";
import { Fragment } from "react";
import { Link, useLocation } from "react-router-dom";

import { useBreadcrumbDetail } from "../context/BreadcrumbContext";
import { breadcrumbFor, type Crumb } from "../routes";

// One declaration for both crumb kinds, at the 14px step Kaizen uses for navigation and chrome --
// the same step as the blurb this row sits above. 12px was the first attempt and was wrong for the
// documented reason: being secondary to the title is a job for colour, not for a smaller size.
const CRUMB = {
  fontSize: "var(--text-14)",
  lineHeight: "var(--leading-lh-150)",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
  maxWidth: "18rem",
} as const;

export function Breadcrumbs() {
  const { pathname } = useLocation();
  const { label, parentLabel, parentPath } = useBreadcrumbDetail();

  const base = breadcrumbFor(pathname);
  // A top-level page is not inside anything. Rendering a one-crumb trail there would repeat the
  // title directly above itself and put a back button next to nowhere to go.
  if (base.length < 2) return null;

  const trail: Crumb[] = [
    ...base.slice(0, -1),
    ...(parentLabel && parentPath ? [{ label: parentLabel, path: parentPath }] : []),
    { label: label || base[base.length - 1].label },
  ];
  // The nearest ancestor, which is the repository when the view named one and the list otherwise.
  // Up rather than browser-back on purpose: back can lead out of the application entirely, and
  // after a reload it leads nowhere at all.
  const up = trail[trail.length - 2];

  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 0.25, minWidth: 0 }}>
      {up.path && (
        <Tooltip title={`Back to ${up.label}`}>
          <IconButton
            component={Link}
            to={up.path}
            size="small"
            aria-label={`Back to ${up.label}`}
            sx={{ mr: 0.25, p: 0.25 }}
          >
            <ArrowLeft size={16} />
          </IconButton>
        </Tooltip>
      )}

      <Box
        component="nav"
        aria-label="Breadcrumb"
        sx={{ display: "flex", alignItems: "center", gap: 0.25, minWidth: 0 }}
      >
        {trail.map((crumb, index) => (
          <Fragment key={`${crumb.path ?? "current"}-${index}`}>
            {index > 0 && (
              <ChevronRight
                size={14}
                aria-hidden
                style={{ color: "var(--text-color-subtle)", flexShrink: 0 }}
              />
            )}
            {crumb.path ? (
              <Box
                component={Link}
                to={crumb.path}
                sx={{
                  ...CRUMB,
                  color: "var(--text-color-secondary)",
                  textDecoration: "none",
                  "&:hover": {
                    color: "var(--text-color-primary)",
                    textDecoration: "underline",
                  },
                }}
              >
                {crumb.label}
              </Box>
            ) : (
              <Box
                component="span"
                aria-current="page"
                sx={{ ...CRUMB, color: "var(--text-color-subtle)" }}
              >
                {crumb.label}
              </Box>
            )}
          </Fragment>
        ))}
      </Box>
    </Box>
  );
}
