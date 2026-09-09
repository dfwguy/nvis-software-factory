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
// routes.test.ts — the route table is data, so it can be checked.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import { describe, expect, it } from "vitest";

import {
  activeViewFor,
  crosswalkPath,
  entityPath,
  NAV_GROUPS,
  repositoryPath,
  routeFor,
  ROUTES,
} from "./routes";

describe("route lookup", () => {
  it("prefers the longest match, so a sub-page does not resolve to its parent", () => {
    // `/contract` is a prefix of `/contract/validate`. Matching the shorter one would highlight
    // the wrong nav item on every contract sub-page.
    expect(routeFor("/contract/validate")?.viewId).toBe("validate");
    expect(routeFor("/contract/map")?.viewId).toBe("mapping-assistant");
    expect(routeFor("/contract")?.viewId).toBe("contract-explorer");
  });

  it("resolves a crosswalk detail path rather than the crosswalk list", () => {
    expect(routeFor("/contract/crosswalk")?.viewId).toBe("crosswalks");
    expect(routeFor("/contract/crosswalk/nautobot")?.viewId).toBe("crosswalk-detail");
  });

  it("has no route for an unknown path", () => {
    expect(routeFor("/nonsense")).toBeUndefined();
  });
});

describe("navigation highlighting", () => {
  it("highlights the list a detail view came from", () => {
    // Otherwise the sidebar shows nothing selected while reading an assessment, and the user
    // loses track of where they are.
    expect(activeViewFor("/assessments/abc123")).toBe("assessments");
    expect(activeViewFor("/repositories/xyz")).toBe("repositories");
    expect(activeViewFor("/golden-path/data-security")).toBe("golden-path");
    expect(activeViewFor("/contract/entity/resource")).toBe("contract-explorer");
    expect(activeViewFor("/contract/crosswalk/redfish")).toBe("crosswalks");
  });
});

describe("path builders", () => {
  it("encodes identifiers, because a repository id can come from a URL", () => {
    expect(repositoryPath("a/b")).toBe("/repositories/a%2Fb");
    expect(entityPath("cooling-path")).toBe("/contract/entity/cooling-path");
    expect(crosswalkPath("bcm netautogen")).toBe("/contract/crosswalk/bcm%20netautogen");
  });
});

describe("the route table", () => {
  it("gives every navigable route a group that the sidebar renders", () => {
    // A route with a group the sidebar does not know about is a page nobody can reach.
    for (const route of ROUTES) {
      if (route.group !== null) expect(NAV_GROUPS).toContain(route.group);
    }
  });

  it("gives every navigable route an icon and a blurb", () => {
    // The toolbar shows the blurb; a missing one leaves the page unexplained.
    for (const route of ROUTES.filter((r) => r.group !== null)) {
      expect(route.icon, `${route.viewId} has no icon`).toBeDefined();
      expect(route.blurb, `${route.viewId} has no blurb`).toBeTruthy();
    }
  });

  it("keeps detail views out of the navigation", () => {
    // A detail view needs an id, so a nav entry pointing at it could only ever 404.
    for (const route of ROUTES.filter((r) => r.path.includes("/:"))) {
      expect(route.group, `${route.viewId} is in the nav but needs a parameter`).toBeNull();
    }
  });

  it("has one route per view id", () => {
    const ids = ROUTES.map((route) => route.viewId);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
