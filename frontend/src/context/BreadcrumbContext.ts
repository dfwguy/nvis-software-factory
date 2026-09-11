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
// BreadcrumbContext.ts — what a detail view can add to its own breadcrumb, no components.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// The route table knows a run is an "Assessment" under "Assessments". It cannot know which run,
// or which repository the run belongs to, because neither is in the URL -- the path carries a
// UUID. Only the view that loaded the data knows, so this is the channel it reports through.
import { createContext, useContext, useEffect } from "react";

export interface BreadcrumbDetail {
  /** Names the page itself, replacing the route's generic label. */
  label?: string;
  /** One hop between the list and this page: the thing this page belongs to. */
  parentLabel?: string;
  parentPath?: string;
}

export interface BreadcrumbValue {
  detail: BreadcrumbDetail;
  set: (detail: BreadcrumbDetail) => void;
}

export const BreadcrumbContext = createContext<BreadcrumbValue>({
  detail: {},
  set: () => {},
});

export const useBreadcrumbDetail = () => useContext(BreadcrumbContext).detail;

/**
 * Name the current page in the breadcrumb, and optionally what it belongs to.
 *
 * Safe to call with `undefined` while the data is still loading — the trail falls back to the
 * route's own label, so the breadcrumb appears immediately and gains the specific name when it
 * arrives, rather than popping into existence halfway through the page load.
 *
 * Call it before any early return. It is a hook, and a view that returns a spinner first would
 * otherwise change its hook count between renders.
 */
export function useBreadcrumb({ label, parentLabel, parentPath }: BreadcrumbDetail): void {
  const { set } = useContext(BreadcrumbContext);
  useEffect(() => {
    set({ label, parentLabel, parentPath });
    // Cleared on the way out so the next page cannot inherit this page's name. React runs this
    // before the incoming view's effects, so navigating detail-to-detail does not flicker.
    return () => set({});
  }, [set, label, parentLabel, parentPath]);
}
